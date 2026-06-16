import typing as t

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types

from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import FunctionParam, Q, UserDefinedFunctionQuery
from sqlleaf.processors.transforms.resolver import find_next_udf_call
from sqlleaf.typing import E


def _find_arg(args: t.List[exp.Expr], param: FunctionParam, index: int) -> t.Optional[exp.Expr]:
    """
    Finds the argument corresponding to a parameter by its name or position.

    Example:
        Given query: SELECT my_func(1, y => 2)
        and parameter 'y',
        we get output 2.
    """
    # 1. Named lookup
    param_name = param.name.lower()
    for arg in args:
        if isinstance(arg, exp.Kwarg):
            arg_key = arg.this
            expr = arg.expression
        elif isinstance(arg, exp.PropertyEQ):
            arg_key = arg.left
            expr = arg.right
        else:
            continue

        is_variadic_call = isinstance(arg_key, exp.Variadic)
        arg_name = (arg_key.this.name if is_variadic_call else arg_key.name).lower()

        if arg_name == param_name:
            if param.is_variadic:
                if isinstance(expr, exp.Array) and not is_variadic_call and not isinstance(expr, exp.Variadic):
                    raise ValueError(
                        f"VARIADIC keyword must be used when passing an array to variadic parameter '{param.name}'"
                    )
                if isinstance(expr, exp.Variadic):
                    return expr.this
                if is_variadic_call:
                    return expr
            return expr

    # 2. Positional lookup
    if index < len(args) and not isinstance(args[index], (exp.Kwarg, exp.PropertyEQ)):
        arg = args[index]
        if not param.is_variadic:
            return arg

        # If the parameter is variadic and the supplied argument is an array,
        # the keyword 'VARIADIC' must also be supplied.
        if isinstance(arg, exp.Array):
            raise ValueError(
                f"VARIADIC keyword must be used when passing an array to variadic parameter '{param.name}'"
            )

        if isinstance(arg, exp.Variadic):
            return arg.this

        # Convert variadic arguments into an array
        # e.g. (1,2,3) -> ARRAY[1,2,3]
        variadic = [a.copy() for a in args[index:] if not isinstance(a, (exp.Kwarg, exp.PropertyEQ))]
        return exp.Array(expressions=variadic) if variadic else None

    return None


def _transform_arguments(
    node: exp.Anonymous, query: UserDefinedFunctionQuery
) -> t.Tuple[t.Dict[str, exp.Expr], t.Dict[str, exp.Expr]]:
    """
    Transforms every argument passed to the UDF into the correct format.

    Example:
        For a UDF with parameters `(x, y)` called as `my_udf(1, y => 2)`, returns:
        param_map = {"x": 1, "y": 2}
        positional_map = {"1": 1, "2": 2}
    """
    param_map = {}
    positional_map = {}
    args = node.expressions

    for i, param in enumerate(query.parameters):
        arg_expr = _find_arg(args, param, i) or param.default

        if arg_expr:
            # If the parameter is a table type and the argument is a ROW expression without a cast,
            # we need to add the cast to the expected type.
            if (
                isinstance(arg_expr, exp.Anonymous)
                and arg_expr.this.lower() == "row"
                and (isinstance(param.type, exp.DataType) and param.type.this == exp.DataType.Type.USERDEFINED)
            ):
                arg_expr = exp.Cast(
                    this=arg_expr,
                    to=exp.DataType(
                        this=exp.DataType.Type.USERDEFINED,
                        kind=exp.Identifier(this=param.name.replace("$", "p"), quoted=False),
                    ),
                )

            param_map[param.name.lower()] = arg_expr
            positional_map[str(i + 1)] = arg_expr

    return param_map, positional_map


def _substitute_parameters(
    replacement_expr: exp.Expr,
    query: UserDefinedFunctionQuery,
    param_map: t.Dict[str, exp.Expr],
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Expr:
    """
    Replaces parameter references within an expression with their corresponding arguments.

    Example:
        Expression: `SELECT $1 + x`
        Maps: param_map={'x': 10}, positional_map={'1': 5}
        Result: `SELECT 5 + 10`
    """
    # 1. Handle case where the root replacement expression itself needs substitution (e.g., expression is just 'x')
    if isinstance(replacement_expr, exp.Column) and not replacement_expr.table:
        col_name = replacement_expr.this.name.lower()
        if col_name in param_map:
            return param_map[col_name].copy()
    elif isinstance(replacement_expr, exp.Parameter):
        param_id = replacement_expr.this.name
        if param_id in positional_map:
            return positional_map[param_id].copy()

    # 2. Walk and replace all references in the expression tree
    for subnode in replacement_expr.walk():
        _substitute_parameter_node(subnode, query, param_map, positional_map)

    return replacement_expr


def _substitute_parameter_node(
    node: exp.Expr,
    query: UserDefinedFunctionQuery,
    param_map: t.Dict[str, exp.Expr],
    positional_map: t.Dict[str, exp.Expr],
) -> None:
    """
    Replaces parameter references and member access for a single node.

    Example:
        Before: `x + $1`
        After: `10 + 5` (where x=10, $1=5)
    """
    replacement = None

    # 1. Determine if this node is a parameter reference and find its replacement
    if isinstance(node, exp.Column) and not node.table:
        col_name = node.this.name.lower()
        if col_name in param_map:
            # In Postgres, if a param name matches a column name in a query with a
            # FROM clause, the column takes precedence.
            parent_select = node.find_ancestor(exp.Select)
            if parent_select:
                for table in parent_select.find_all(exp.Table):
                    table_query = query.object_mapping.lookup_table_query(table)
                    if table_query and col_name in [c.name for c in table_query.get_column_defs()]:
                        return

            replacement = param_map[col_name]
    elif isinstance(node, exp.Parameter):
        param_id = node.this.name
        if param_id in positional_map:
            replacement = positional_map[param_id]

    # 2. Apply replacement if found
    if replacement is not None:
        # Avoid replacing the left side of a Dot (member access), as it's handled separately
        if not (isinstance(node.parent, exp.Dot) and node.arg_key == "this"):
            replacement = replacement.copy()

            # Wrap cast in parentheses if it's being indexed to ensure valid PostgreSQL syntax
            # e.g. (ARRAY[]::numeric[])[i]
            if isinstance(node.parent, exp.Bracket) and isinstance(replacement, exp.Cast):
                replacement = exp.Paren(this=replacement)

            node.replace(replacement)

    # 3. Handle member access (e.g. SELECT x.name)
    elif isinstance(node, exp.Dot):
        _replace_dot_reference(node, param_map, positional_map)


def _ensure_from_clauses(expression: exp.Expr, param_map: t.Dict[str, exp.Expr]) -> exp.Expr:
    """
    Ensures SELECT statements have appropriate FROM clauses when using table-derived columns.

    Example:
        Before: `SELECT p.name` (where p is a table-type argument)
        After: `SELECT p.name FROM p`
    """
    for select in expression.find_all(exp.Select):
        if not select.args.get("from"):
            # Check if any Dot nodes now refer to a table name we can use
            for dot in select.find_all(exp.Dot):
                table_name = None
                if isinstance(dot.this, exp.Identifier):
                    table_name = dot.this.name
                elif isinstance(dot.this, exp.Paren) and isinstance(dot.this.this, exp.Cast):
                    data_type = dot.this.this.args.get("to")
                    if isinstance(data_type, exp.DataType):
                        table_name = data_type.sql().lower()

                if table_name and _is_table_from_params(table_name, param_map):
                    # Add FROM table_name to this SELECT
                    select.from_(table_name, copy=False)
                    break
    return expression


def _is_table_from_params(table_name: str, param_map: t.Dict[str, exp.Expr]) -> bool:
    """
    Checks if a table name corresponds to one of the provided arguments.

    Example:
        `_is_table_from_params("people", {"$1": people})` -> `True`
    """
    for arg in param_map.values():
        if isinstance(arg, exp.Column):
            if arg.table == table_name or (not arg.table and arg.this.name == table_name):
                return True
        elif isinstance(arg, exp.Table) and arg.name == table_name:
            return True
        elif isinstance(arg, exp.Cast):
            data_type = arg.args.get("to")
            if isinstance(data_type, exp.DataType) and data_type.sql().lower() == table_name.lower():
                return True
    return False


def _replace_dot_reference(
    node: exp.Dot, param_map: t.Dict[str, exp.Expr], positional_map: t.Dict[str, exp.Expr]
) -> None:
    """
    Replacements related to member access on parameters (e.g., $1.field -> table.field).

    Example:
        Before: `$1.name` (where $1 is a table-type argument 'people')
        After: `people.name`
    """
    # 1. Substitute the left side if it's a parameter
    left = node.left
    sub = (
        param_map.get(left.this.name.lower())
        if isinstance(left, exp.Column) and not left.table
        else positional_map.get(left.this.name)
        if isinstance(left, exp.Parameter)
        else None
    )

    if not sub:
        return

    # 2. Extract table name from the substituted expression
    table_name = (
        sub.table or (sub.this.name if isinstance(sub.this, exp.Identifier) else None)
        if isinstance(sub, exp.Column)
        else sub.name
        if isinstance(sub, exp.Table)
        else None
    )

    if table_name:
        node.set("this", exp.Identifier(this=table_name, quoted=False))
    elif isinstance(sub, exp.Cast):
        # Wrap cast in parentheses so we can look up fields on it, e.g. (ROW(...)::type).field
        node.set("this", exp.Paren(this=sub.copy()))


def _transform_row_to_subquery(
    node: exp.Cast, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> t.Optional[exp.Expr]:
    """
    Transforms the ROW(...)::table_name pattern into a SELECT subquery.

    Example:
        Query: `SELECT ROW(1, 'abc')::my_table` where `my_table` has two columns.
        Result: `ROW(1, 'abc')::my_table` -> `(SELECT 1, 'abc')`
    """
    # TODO: put this in a generic 'transform' location
    # 1. Check if this is a ROW(...) cast to a known table
    data_type = node.args.get("to")
    if not isinstance(data_type, exp.DataType):
        return None

    type_name = data_type.sql().lower()
    table = exp.table_(table=type_name)
    table_query = query.object_mapping.lookup_table_query(table=table, raise_on_missing=False)
    if not table_query:
        raise SqlLeafException(message=f"Unknown table in cast to ROW(): {type_name}")

    row_expr = node.this

    # Ensure column count matches
    columns = table_query.get_column_defs()
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


def _create_subquery_with_alias(replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> exp.Subquery:
    """Creates a Subquery with a table alias 't' and the UDF's return columns."""
    return exp.Subquery(
        this=replacement_expr,
        alias=exp.TableAlias(
            this=exp.Identifier(this="t", quoted=False),
            columns=[exp.Identifier(this=c, quoted=False) for c in query.return_columns],
        ),
    )


def _create_lateral_replacement(
    target_node: exp.Expr, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> None:
    """
    Wraps a replacement expression for use in a LATERAL context and applies it.

    Example:
        Before: `SELECT * FROM table1, LATERAL hello()`
        After: `SELECT * FROM table1, LATERAL (SELECT * FROM (SELECT ...) AS t(name, age))`
        where hello() returns (name, age)
    """
    if query.return_columns:
        # Reconstruct the desired structure manually to avoid sqlglot's select().from_() overhead
        subquery_replacement = _create_subquery_with_alias(replacement_expr, query)
        replacement = exp.Paren(
            this=exp.Select(
                expressions=[exp.Star()],
                from_=exp.From(this=subquery_replacement),
            )
        )
    else:
        # For non-table returning UDFs in LATERAL context
        # (though LATERAL usually implies table-returning)
        replacement = exp.Paren(this=replacement_expr)

    target_node.replace(replacement)


def _transform_udf_to_subquery_if_table_reference(
    node: exp.Anonymous, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> None:
    """
    Transforms a UDF call into a subquery when used in a FROM clause as a table.

    Example:
        SELECT FROM hello() -> SELECT FROM (SELECT ...) AS t(name, age)
        where hello() returns (name, age)
    """
    if query.return_columns:
        replacement_expr = _create_subquery_with_alias(replacement_expr, query)
    else:
        if isinstance(replacement_expr, (exp.Select, exp.Values)):
            replacement_expr = exp.Paren(this=replacement_expr)

    if isinstance(node.parent, exp.Lateral):
        _create_lateral_replacement(node, replacement_expr, query)
    else:
        node.parent.replace(replacement_expr)


def _get_dot_node(target_node: exp.Expr) -> t.Optional[exp.Dot]:
    """
    Identifies if the UDF call is followed by a member access (Dot).
    """
    parent = target_node.parent
    if isinstance(parent, exp.Dot):
        # Case: hello('John').name
        return parent
    if isinstance(parent, exp.Paren) and isinstance(parent.parent, exp.Dot):
        # Case: (hello('John')).name
        return parent.parent
    return None


def _transform_field_access_to_subquery(
    dot_node: exp.Dot, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> None:
    """
    Transforms a UDF with a field access into a subquery with the field selected.

    Example:
        Before: `(hello('John')).name`
        After: `(SELECT name FROM (SELECT 'John', 50) AS t(name, age))`

    This is necessary because SQL doesn't allow direct field access on a subquery/UDF call
    without treating it as a table source or using a subquery. Returning a Subquery
    ensures the field access is correctly scoped and valid SQL.
    """
    field_name = dot_node.expression.name
    subquery = exp.select(field_name).from_(_create_subquery_with_alias(replacement_expr, query))
    dot_node.replace(exp.Paren(this=subquery))


def _replace_scalar_call(target_node: exp.Expr, replacement_expr: exp.Expr) -> None:
    """
    Replaces a scalar UDF call, wrapping query-like expressions in parentheses.

    Example:
        Given hello() as `SELECT 1`,
        Before: `SELECT hello()`
        After: `SELECT (SELECT 1)`
    """
    if isinstance(replacement_expr, (exp.Select, exp.Values)):
        replacement_expr = exp.Paren(this=replacement_expr)
    target_node.replace(replacement_expr.copy())


def _get_target_node(node: exp.Anonymous) -> exp.Expr:
    """
    Returns the node to be replaced.
    """
    parent = node.parent
    # Qualified with a schema (e.g., myschema.myfunc())
    if isinstance(parent, exp.Dot) and isinstance(parent.left, exp.Identifier):
        return parent
    return node


def _transform_inner_query(
    stmt: exp.Expr,
    param_map: t.Dict[str, exp.Expr],
    query: UserDefinedFunctionQuery,
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Expr:
    """
    Performs replacement and transformations over a UDF's inner query.
    """
    # 1. Substitute parameter references
    replacement_expr = _substitute_parameters(stmt, query, param_map, positional_map)

    # 2. Perform additional transformations
    # Handle ROW(...)::table_name replacement (composite/table type casting)
    for subnode in replacement_expr.walk():
        if isinstance(subnode, exp.Cast):
            row_expr = subnode.this
            if isinstance(row_expr, exp.Anonymous) and row_expr.this.lower() == "row":
                # Don't replace if it's being used for field access, as it's likely
                # already been handled or needs to be preserved.
                if not isinstance(subnode.parent, exp.Paren) or not isinstance(subnode.parent.parent, exp.Dot):
                    if subnode is not replacement_expr:
                        new_expr = _transform_row_to_subquery(subnode, replacement_expr)
                        if new_expr:
                            replacement_expr = new_expr

    new_expr = _ensure_from_clauses(replacement_expr, param_map)
    return new_expr


def _build_replacement_exprs(node: exp.Anonymous, query: UserDefinedFunctionQuery) -> t.List[exp.Expr]:
    """Builds the expressions that will replace a UDF call."""
    if query.return_type and query.return_type.this == exp.DataType.Type.NULL:
        return [exp.select(exp.Null())]

    param_map, positional_map = _transform_arguments(node, query)

    replacement_exprs = []
    for stmt in query.inner_statements:
        # Annotate types of the inner UDF query before transformation
        stmt = annotate_types(stmt.copy(), schema=query.object_mapping)
        replacement_exprs.append(_transform_inner_query(stmt, query, param_map, positional_map))

    return replacement_exprs


def _apply_replacement(target_node: exp.Expr, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> None:
    """Applies the replacement of a UDF call node with its body logic."""
    dot_node = _get_dot_node(target_node)

    if isinstance(target_node.parent, exp.Lateral):
        _create_lateral_replacement(target_node, replacement_expr, query)
    elif isinstance(target_node.parent, exp.Table):
        _transform_udf_to_subquery_if_table_reference(target_node, replacement_expr, query)
    elif bool(query.return_columns and dot_node):  # A field
        _transform_field_access_to_subquery(dot_node, replacement_expr, query)
    else:
        _replace_scalar_call(target_node, replacement_expr)


def substitute_udf(statement: E, query: Q) -> t.List[exp.Expr]:
    """
    Inlines UDF calls in a SQL string with their defined bodies and parameters.

    Example:
        substitute_udf("SELECT hello('world')", [hello_udf])
        -> ["SELECT (SELECT 'Hello ' || 'world')"]
    """
    result = []
    while True:
        # Annotate types to help with function overloading resolution
        expression = annotate_types(statement, dialect=query.dialect, schema=query.object_mapping)

        # Find the next UDF call to substitute
        to_replace, matched_udf = find_next_udf_call(expression, query.object_mapping)
        if not to_replace:
            break

        result = [expression]

        target_node = _get_target_node(to_replace)
        replacement_exprs = _build_replacement_exprs(to_replace, matched_udf)

        if len(replacement_exprs) > 1:
            # Handles UDFs returning multiple statements by branching the entire query.
            # Each branch is then recursively processed to handle any remaining UDF calls.
            node_index = next((i for i, n in enumerate(expression.walk()) if n is target_node), -1)
            if node_index == -1:
                return [expression]

            final_results = []
            for repl_expr in replacement_exprs:
                new_expression = expression.copy()
                for i, n in enumerate(new_expression.walk()):
                    if i == node_index:
                        _apply_replacement(n, repl_expr, matched_udf)
                        break

                # Apply the substitution recursively
                final_results.extend(substitute_udf(new_expression, query))
            return final_results

        # Single statement: apply replacement and continue finding next UDF calls
        _apply_replacement(target_node, replacement_exprs[0], matched_udf)

    return result
