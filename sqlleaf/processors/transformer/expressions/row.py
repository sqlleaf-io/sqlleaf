import logging
import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import Q, UserDefinedFunctionQuery

logger = logging.getLogger("sqlleaf")


def add_parens_for_composite_field_access(statement: exp.Expr) -> exp.Expr:
    """
    Ensure parentheses surround composite field dereference on expressions used with dot notation.

    Example:
        CAST(ROW(2) AS people).age -> (CAST(ROW(2) AS people)).age
    """
    for dot in statement.find_all(exp.Dot):
        left = dot.this
        if isinstance(left, exp.Cast) and util.is_row_function(left.this):
            dot.set("this", exp.Paren(this=left.copy()))
    return statement


def simplify_row_in_values(values_expr: exp.Values, dialect: str) -> None:
    """
    Simplify MySQL's VALUES ROW(...) syntax by flattening the ROW() function.

    Example:
        VALUES (ROW(1, 2)), (ROW(3, 4)) -> VALUES (1, 2), (3, 4)
    """
    if dialect == "mysql":
        for tuple_node in values_expr.expressions:
            if isinstance(tuple_node, exp.Tuple) and len(tuple_node.expressions) == 1:
                inner = tuple_node.expressions[0]
                if util.is_row_function(inner):
                    tuple_node.set("expressions", [e.copy() for e in inner.expressions])


def simplify_row(statement: exp.Expr, query: Q) -> None:
    """
    Simplify occurrences of the ROW() function.

    ROW() is used to group multiple values into a single composite value. Its default output is an anonymous record.
    It can often be simplified depending on where it appears in a query. We focus on:
    - field access: `(ROW(e1, e2, e3)::my_type).field_n` -> `en AS field_n`
    - star access: `(ROW(e1, e2, e3)::my_type).*` -> `e1 AS a, e2 AS b, e3 AS c`

    Transformation is skipped when the ROW() cast is inside functions like UNNEST/ARRAY.
    """
    if row_nodes := _collect_row_functions(statement):
        _expand_row_cast_aliases(row_nodes, statement, query)
        _simplify_field_access(row_nodes, statement, query)


def _collect_row_functions(statement: exp.Expr) -> t.Set[exp.Anonymous]:
    """
    Collect all ROW() expressions from the statement.
    """
    return {node for node in statement.find_all(exp.Anonymous) if node.name.upper() == "ROW"}


def _expand_row_cast_aliases(row_nodes: t.Set[exp.Anonymous], statement: exp.Expr, query: Q) -> None:
    """
    Expand ROWs with casts into lists of columns, as well as expressions of the form '(alias_name).field'.

    Examples:
        `SELECT ROW(a, b)::my_type AS r` -> `SELECT a AS a, b AS b`
        `SELECT (r).a FROM (SELECT ROW(a, b)::my_type AS r) AS sub` -> `SELECT sub.a AS a FROM (SELECT a AS a, b AS b) AS sub`
    """
    for row_node in row_nodes:
        cast_node = row_node.parent
        if not isinstance(cast_node, exp.Cast):
            continue

        alias_node = cast_node.parent
        if not isinstance(alias_node, exp.Alias):
            continue

        if _is_inside_unnest(alias_node):
            continue

        if not _is_direct_select_expression(alias_node):
            continue

        to_type = cast_node.to.find(exp.Identifier)
        if to_type is None:
            continue

        fields = _lookup_type_fields(to_type.name, query)
        if not fields:
            continue

        row_exprs = cast_node.this.expressions

        _rewrite_field_references(alias_node, row_exprs, fields, statement)
        _expand_to_select_list(alias_node, row_exprs, fields)


def _simplify_field_access(row_nodes: t.Set[exp.Anonymous], statement: exp.Expr, query: Q) -> None:
    """
    Simplify field access patterns on ROW casts.

    Examples:
        `(ROW(a, b, c)::my_type).a` -> `a`
        `(ROW(a, b, c)::my_type).*` -> `a AS a, b AS b, c AS c`
        `(CASE WHEN x THEN ROW(a, b)::t ELSE ROW(0, 0)::t END).a` -> `CASE WHEN x THEN a ELSE 0 END`
    """
    for dot in statement.find_all(exp.Dot):
        if dot.parent is None and dot is not statement:
            continue

        left = dot.this.unnest()
        right = dot.expression

        cast_node = _get_row_cast(left, row_nodes)
        if cast_node is not None:
            _simplify_field_of_row(dot, cast_node, right, query)
        elif left in row_nodes and isinstance(right, exp.Star):
            _simplify_star_of_uncast_row(dot, left)
        elif isinstance(left, exp.Case) and isinstance(right, exp.Identifier):
            _simplify_field_of_case_row(dot, left, right, query, row_nodes)
        elif isinstance(left, exp.Column) and isinstance(right, exp.Identifier):
            _simplify_column_field_access(dot, left, right)


def _simplify_star_of_uncast_row(dot: exp.Dot, row_node: exp.Anonymous) -> None:
    """
    Handle (ROW(e1, e2, e3)).* pattern without a typecast.

    In Postgres, the default aliases for ROW() fields accessed via .* are f1, f2, f3, ...

    Examples:
        `(ROW('Alice'::text, 25, 10.0)).*` -> `'Alice'::text AS f1, 25 AS f2, 10.0 AS f3`
    """
    aliases = [f"f{i + 1}" for i in range(len(row_node.expressions))]
    _expand_to_select_list(dot, row_node.expressions, aliases)


def _simplify_column_field_access(dot: exp.Dot, column: exp.Column, field: exp.Identifier) -> None:
    """
    Rewrite `(col).field` into a plain `col.field` Column expression.

    In Postgres, `(u).a` is composite field access on a column alias; the parentheses
    are syntactic and should be removed before qualification so that the optimizer
    does not double-qualify the table name (e.g. `u.u.a`).

    Examples:
        `(u).a` -> `u.a`
        `(sub.r).b` -> `sub.r.b` (handled by sqlglot as Dot)
    """
    table = column.args.get("table")
    if table is not None:
        # col already has a table qualifier: keep as Dot(column, field)
        new_col = exp.Dot(this=column.copy(), expression=field.copy())
    else:
        new_col = exp.column(field.name, table=column.name)
    dot.replace(new_col)


def _resolve_field_index(cast_node: exp.Cast, field_name: str, query: Q) -> t.Optional[t.Tuple[t.List[str], int]]:
    """
    Look up the field index for `field_name` in the composite type of `cast_node`.
    Returns (fields, index) or None if the type or field is unknown.

    Examples:
        Given `ROW(a, b)::my_type` where `my_type` has fields `(x, y)`:
        `_resolve_field_index(cast_node, "y", query)` -> `(["x", "y"], 1)`
        `_resolve_field_index(cast_node, "z", query)` -> `None`
    """
    type_id = cast_node.to.find(exp.Identifier)
    if type_id is None:
        return None
    fields = _lookup_type_fields(type_id.name, query)
    if not fields or field_name not in fields:
        return None
    return fields, fields.index(field_name)


def _simplify_field_of_row(dot: exp.Dot, cast_node: exp.Cast, right: exp.Expr, query: Q) -> None:
    """
    Handle (ROW(...)::my_type).field or (ROW(...)::my_type).* patterns.

    Examples:
        `(ROW(a, b, c)::my_type).b` -> `b`
        `(ROW(a, b, c)::my_type).*` -> `a AS a, b AS b, c AS c`
    """
    if isinstance(right, exp.Star):
        type_id = cast_node.to.find(exp.Identifier)
        if type_id is None:
            return
        fields = _lookup_type_fields(type_id.name, query)
        if fields:
            _expand_to_select_list(dot, cast_node.this.expressions, fields)
    else:
        if resolved := _resolve_field_index(cast_node, right.name, query):
            _, idx = resolved
            dot.replace(_extract_field(cast_node, idx))


def _simplify_field_of_case_row(
    dot: exp.Dot,
    case_node: exp.Case,
    right: exp.Identifier,
    query: Q,
    row_node_set: t.Set[exp.Anonymous],
) -> None:
    """Simplify CASE statements when a field selector is used on its result.

    Examples:
        `(CASE WHEN x > 1 THEN ROW(a, b)::t ELSE ROW(0, '')::t END).a` -> `CASE WHEN x > 1 THEN a ELSE 0 END`
    """
    branch_casts: t.List[exp.Cast] = []
    for if_node in case_node.args.get("ifs", []):
        c = _get_row_cast(if_node.args.get("true").unnest(), row_node_set)
        if c is None:
            return
        branch_casts.append(c)

    default_cast = _get_row_cast(case_node.args.get("default").unnest(), row_node_set)
    if not branch_casts or default_cast is None:
        return

    if _is_inside_unnest(dot):
        return

    if resolved := _resolve_field_index(branch_casts[0], right.name, query):
        _, field_index = resolved
        dot.replace(_replace_row_casts_in_case(case_node, field_index))


def _is_direct_select_expression(node: exp.Expr) -> bool:
    """Check if a node is a direct child of a SELECT expressions list.

    `SELECT <node>, ...` -> True
    `SELECT func(<node>)` -> False
    """
    return isinstance(node.parent, exp.Select) and node in node.parent.expressions


def _find_subquery_table_alias(select_parent: exp.Expr) -> t.Optional[str]:
    """
    Walk up from a SELECT to find a Subquery or Lateral with an alias.
    """
    p = select_parent.parent
    while p is not None:
        if isinstance(p, (exp.Subquery, exp.Lateral)) and p.alias:
            return p.alias
        if isinstance(p, exp.CTE):
            break
        p = p.parent
    return None


def _rewrite_field_references(
    alias_node: exp.Alias, row_exprs: t.List[exp.Expr], fields: t.List[str], statement: exp.Expr
) -> None:
    """Rewrite (alias_name).field references to the associated column or expression.

    There are two cases to consider:
    1. When the ROW cast alias lives inside a subquery, dot references in the outer query
    are rewritten to qualified column references using the subquery's table alias.
    Given type `t` with fields (x, y):
        `SELECT (r).x FROM (SELECT ROW(a, b)::t AS r FROM t1) AS sub`
        -> `SELECT sub.x AS x FROM (SELECT a AS x, b AS y FROM t1) AS sub`

    2. When the ROW cast alias lives in a CTE or top-level query (no subquery alias),
    dot references are inlined with the original ROW expressions.
    Given type `t` with fields (x, y):
        `SELECT (r).x FROM (SELECT ROW(a + 1, b)::t AS r FROM t1)`
        -> `SELECT a + 1 AS x FROM (SELECT a + 1 AS x, b AS y FROM t1)`
    """
    subquery_table_alias = _find_subquery_table_alias(alias_node)

    for dot in statement.find_all(exp.Dot):
        inner_col = dot.this.unnest()
        dot_right = dot.expression
        if not (
            isinstance(inner_col, exp.Column)
            and inner_col.name == alias_node.alias
            and isinstance(dot_right, exp.Identifier)
            and dot_right.name in fields
        ):
            continue

        field_name = dot_right.name
        if subquery_table_alias:
            replacement = exp.alias_(exp.column(field_name, table=subquery_table_alias), field_name)
        else:
            field_idx = fields.index(field_name)
            replacement = exp.alias_(row_exprs[field_idx].copy(), field_name)
        dot.replace(replacement)


def _expand_to_select_list(node: exp.Expr, expressions: t.List[exp.Expr], aliases: t.List[str]) -> None:
    """
    Expand a node into multiple aliased expressions in its parent SELECT list.

    Example:
        `SELECT ROW(a, b)::my_type AS r` with expressions=[a, b] and aliases=["x", "y"]:
        `node` (the alias `r`) is replaced in-place -> `SELECT a AS x, b AS y`
    """
    if not _is_direct_select_expression(node):
        return

    select_node = node.parent
    idx = select_node.expressions.index(node)
    new_exprs = [exp.alias_(expressions[i].copy(), aliases[i]) for i in range(len(aliases))]
    select_node.set(
        "expressions",
        select_node.expressions[:idx] + new_exprs + select_node.expressions[idx + 1 :],
    )


def _is_row_cast(node: exp.Expr) -> bool:
    """
    Check if a node is a Cast of a ROW() to a USERDEFINED type.
    """
    return (
        isinstance(node, exp.Cast) and util.is_row_function(node.this) and node.to.this == exp.DataType.Type.USERDEFINED
    )


def _get_row_cast(inner: exp.Expr, row_node_set: t.Set[exp.Anonymous]) -> t.Optional[exp.Cast]:
    """
    Return the Cast node if it wraps a ROW().

    Examples:
        `(ROW(a, b)::my_type)` -> Cast node
    """
    return inner if _is_row_cast(inner) and inner.this in row_node_set else None


def _is_inside_unnest(node: exp.Expr) -> bool:
    """
    Check if a node is nested inside an UNNEST or ARRAY expression.

    Examples:
        `UNNEST(ARRAY(SELECT ROW(a)::t FROM t1))` -> True
    """
    return node.find_ancestor(exp.Unnest, exp.Array) is not None


def _lookup_type_fields(type_name: str, query: Q) -> t.List[str]:
    """
    Return ordered field names for a composite type.

    Examples:
        Given a type `my_type` defined as `CREATE TYPE my_type AS (x INT, y TEXT)`:
        `_lookup_type_fields("my_type", query)` -> `["x", "y"]`
        `_lookup_type_fields("unknown_type", query)` -> `[]`
    """
    type_table = exp.Table(this=exp.to_identifier(type_name))
    type_query = query.object_mapping.lookup_type_query(table=type_table, raise_on_missing=False)
    if type_query is None:
        return []
    return [c.name for c in type_query.get_column_defs()]


def _extract_field(cast_node: exp.Cast, field_index: int) -> exp.Expr:
    """
    Return the k-th expression from the ROW() constructor.

    Example:
        `CAST(ROW(a, b, c) AS my_type), field_index=1` -> `b`
    """
    return cast_node.this.expressions[field_index].copy()


def _replace_row_casts_in_case(case_node: exp.Case, field_index: int) -> exp.Case:
    """
    Replace every Cast(ROW(...), my_type) inside a Case expression with
    the field_index-th ROW argument.

    Examples:
        `CASE WHEN x THEN ROW(a, b)::t ELSE ROW(0, '')::t END, field_index=0` -> `CASE WHEN x THEN a ELSE 0 END`
    """
    new_case = case_node.copy()
    for cast in new_case.find_all(exp.Cast):
        if _is_row_cast(cast):
            cast.replace(_extract_field(cast, field_index))
    return new_case


def transform_row_function_to_subquery(replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> exp.Expr:
    """Transform a ROW() function into a subquery."""
    transformed = False

    for cast_node in list(replacement_expr.find_all(exp.Cast)):
        row_expr = cast_node.this
        if util.is_row_function(row_expr):
            # Don't replace if it's being used for field access, as it's likely
            # already been handled or needs to be preserved.
            if not (isinstance(cast_node.parent, exp.Paren) and isinstance(cast_node.parent.parent, exp.Dot)):
                if cast_node is not replacement_expr:
                    new_expr = transform_row_to_subquery(cast_node, replacement_expr, query)
                    if new_expr:
                        transformed = True
                        replacement_expr = new_expr
    if transformed:
        logger.debug(f"Replaced ROW() to subquery: {replacement_expr.sql(dialect='postgres')}")
    return replacement_expr


def transform_row_to_subquery(
    node: exp.Cast, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> t.Optional[exp.Expr]:
    """
    Transforms the ROW(...)::table_name pattern into a SELECT subquery.

    Example:
        Query: `SELECT ROW(1, 'abc')::my_table` where `my_table` has two columns.
        Result: `ROW(1, 'abc')::my_table` -> `(SELECT 1, 'abc')`
    """
    # 1. Check if this is a ROW(...) cast to a known table
    data_type = node.args.get("to")
    if not isinstance(data_type, exp.DataType):
        return None

    type_name = data_type.sql().lower()
    table = exp.to_table(type_name)
    object_query = query.object_mapping.lookup_table_query(table=table, raise_on_missing=False)
    if not object_query:
        object_query = query.object_mapping.lookup_type_query(table=table, raise_on_missing=False)
        if not object_query:
            raise SqlLeafException(message=f"Unknown table or type in cast to ROW(): {type_name}")

    row_expr = node.this

    # Ensure column count matches
    columns = object_query.get_column_defs()
    if len(row_expr.expressions) != len(columns):
        return None

    # 2. Convert to SELECT
    new_node = exp.select(*(val.copy() for val in row_expr.expressions))

    # 3. Apply replacement, lifting if inside a single-expression SELECT
    parent = node.parent
    if not parent:
        return new_node if node is replacement_expr else None

    if isinstance(parent, exp.Select) and len(parent.expressions) == 1:
        if parent is replacement_expr:
            return new_node
        parent.replace(new_node)
    else:
        node.replace(exp.Paren(this=new_node))

    return None
