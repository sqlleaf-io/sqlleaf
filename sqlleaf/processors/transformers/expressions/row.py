import typing as t

from sqlglot import exp

from sqlleaf.models.query import Query


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
                if isinstance(inner, exp.Anonymous) and inner.this.upper() == "ROW":
                    tuple_node.set("expressions", [e.copy() for e in inner.expressions])


def simplify_row(statement: exp.Expr, query: Query) -> None:
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


def _collect_row_functions(statement: exp.Expr) -> t.List[exp.Anonymous]:
    """
    Collect all ROW() expressions from the statement.
    """
    return [node for node in statement.find_all(exp.Anonymous) if node.name.upper() == "ROW"]


def _expand_row_cast_aliases(row_nodes: t.List[exp.Anonymous], statement: exp.Expr, query: Query) -> None:
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
        _expand_alias_to_fields(alias_node, row_exprs, fields)


def _simplify_field_access(row_nodes: t.List[exp.Anonymous], statement: exp.Expr, query: Query) -> None:
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


def _simplify_field_of_row(dot: exp.Dot, cast_node: exp.Cast, right: exp.Expr, query: Query) -> None:
    """
    Handle (ROW(...)::my_type).field or (ROW(...)::my_type).* patterns.

    Examples:
        `(ROW(a, b, c)::my_type).b` -> `b`
        `(ROW(a, b, c)::my_type).*` -> `a AS a, b AS b, c AS c`
    """
    type_name = cast_node.to.find(exp.Identifier)
    if type_name is None:
        return

    fields = _lookup_type_fields(type_name.name, query)
    if not fields:
        return

    if isinstance(right, exp.Star):
        _expand_to_select_list(dot, cast_node.this.expressions, fields)
    else:
        field_name = right.name
        if field_name not in fields:
            return

        field_index = fields.index(field_name)
        dot.replace(_extract_field(cast_node, field_index))


def _simplify_field_of_case_row(
    dot: exp.Dot,
    case_node: exp.Case,
    right: exp.Identifier,
    query: Query,
    row_node_set: t.List[exp.Anonymous],
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

    type_name = branch_casts[0].to.find(exp.Identifier)
    if type_name is None:
        return

    fields = _lookup_type_fields(type_name.name, query)
    if not fields:
        return

    field_name = right.name
    if field_name not in fields:
        return

    field_index = fields.index(field_name)
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


def _expand_alias_to_fields(alias_node: exp.Alias, row_exprs: t.List[exp.Expr], fields: t.List[str]) -> None:
    """Expand a single ROW cast alias into individual field aliases in the SELECT list.

    Examples:
        `SELECT ROW(a, b, c)::my_type AS r` -> `SELECT a AS a, b AS b, c AS c`
    """
    _expand_to_select_list(alias_node, row_exprs, fields)


def _expand_to_select_list(node: exp.Expr, expressions: t.List[exp.Expr], aliases: t.List[str]) -> None:
    """Expand a node into multiple aliased expressions in its parent SELECT list."""
    if not _is_direct_select_expression(node):
        return

    select_node = node.parent
    idx = select_node.expressions.index(node)
    new_exprs = [exp.alias_(expressions[i].copy(), aliases[i]) for i in range(len(aliases))]
    select_node.set(
        "expressions",
        select_node.expressions[:idx] + new_exprs + select_node.expressions[idx + 1 :],
    )


def _get_row_cast(inner: exp.Expr, row_node_set: t.List[exp.Anonymous]) -> t.Optional[exp.Cast]:
    """Return the Cast node if it wraps a ROW().

    Examples:
        `(ROW(a, b)::my_type)` -> Cast node
    """
    # inner = node.unnest()
    if isinstance(inner, exp.Cast) and inner.this in row_node_set and inner.to.this == exp.DataType.Type.USERDEFINED:
        return inner
    return None


def _is_inside_unnest(node: exp.Expr) -> bool:
    """Return True if node is nested inside an UNNEST or ARRAY expression.

    Examples:
        `UNNEST(ARRAY(SELECT ROW(a)::t FROM t1))` -> True
    """
    return node.find_ancestor(exp.Unnest, exp.Array) is not None


def _lookup_type_fields(type_name: str, query: Query) -> t.List[str]:
    """
    Return ordered field names for a composite type.
    """
    type_table = exp.Table(this=exp.to_identifier(type_name))
    type_query = query.object_mapping.lookup_type_query(table=type_table, raise_on_missing=False)
    if type_query is None:
        return []
    return [c.name for c in type_query.get_column_defs()]


def _extract_field(cast_node: exp.Cast, field_index: int) -> exp.Expr:
    """
    Return the k-th expression from the ROW() constructor.

    Examples:
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
        if (
            isinstance(cast.this, exp.Anonymous)
            and cast.this.name.upper() == "ROW"
            and cast.to.this == exp.DataType.Type.USERDEFINED
        ):
            cast.replace(_extract_field(cast, field_index))
    return new_case
