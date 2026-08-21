import logging
import typing as t

from sqlglot import exp

from sqlleaf import mappings, util, exception
from sqlleaf.models.query import CallQuery, CTASQuery, ExecuteQuery, FunctionParam, UserDefinedFunctionQuery

logger = logging.getLogger("sqlleaf")


def find_arg(args: t.List[exp.Expr], param: FunctionParam, index: int) -> t.Optional[exp.Expr]:
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
                    raise exception.MappingError(
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
            raise exception.MappingError(
                f"VARIADIC keyword must be used when passing an array to variadic parameter '{param.name}'"
            )

        if isinstance(arg, exp.Variadic):
            return arg.this

        # Convert variadic arguments into an array
        # e.g. (1,2,3) -> ARRAY[1,2,3]
        variadic = [a.copy() for a in args[index:] if not isinstance(a, (exp.Kwarg, exp.PropertyEQ))]
        return exp.Array(expressions=variadic) if variadic else None

    return None


def transform_arguments(
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

    logger.debug(f"Transforming arguments for UDF: {query.name}")

    for i, param in enumerate(query.parameters):
        arg_expr = find_arg(args, param, i) or param.default

        if arg_expr:
            # Normalize people.* to people
            if isinstance(arg_expr, exp.Column) and arg_expr.this.name == "*":
                arg_expr = exp.column(arg_expr.table)
            elif isinstance(arg_expr, exp.TableColumn):
                arg_expr = exp.column(arg_expr.this)

            # If the parameter is a table type and the argument is a ROW expression without a cast,
            # we need to add the cast to the expected type.
            if util.is_row_function(arg_expr) and (
                isinstance(param.type, exp.DataType) and param.type.this == exp.DataType.Type.USERDEFINED
            ):
                arg_expr = exp.Cast(
                    this=arg_expr,
                    to=param.type.copy(),
                )

            param_map[param.name.lower()] = arg_expr
            positional_map[str(i + 1)] = arg_expr

    return param_map, positional_map


def substitute_parameters(
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
        substitute_parameter_node(subnode, query, param_map, positional_map)

    return replacement_expr


def substitute_parameter_node(
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
        replace_dot_reference(node, param_map, positional_map)


def replace_dot_reference(
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
        if isinstance(left, (exp.Parameter, exp.Placeholder))
        else None
    )
    if not sub:
        return

    # 2. Extract table name from the substituted expression
    table_name = (
        sub.table or (sub.this.name if isinstance(sub.this, exp.Identifier) else None)
        if isinstance(sub, exp.Column)
        else sub.this.name
        if isinstance(sub, exp.TableColumn)
        else sub.name
        if isinstance(sub, exp.Table)
        else None
    )

    if table_name:
        node.replace(exp.Column(table=exp.Identifier(this=table_name, quoted=False), this=node.right.copy()))
    elif isinstance(sub, exp.Cast):
        # Wrap cast in parentheses so we can look up fields on it, e.g. (ROW(...)::type).field
        node.set("this", exp.Paren(this=sub.copy()))


def substitute_call(query: CallQuery) -> t.List[exp.Expr]:
    """
    Substitutes a CALL statement with the body of the procedure it calls.
    Circular references in procedure-to-procedure calls could cause infinite recursion.
    """
    procedure_table = exp.Table(
        this=exp.to_identifier(query.procedure),
        db=exp.to_identifier(query.schema) if query.schema else None,
    )
    matched_proc = query.object_mapping.lookup_procedure_query(procedure_table, raise_on_missing=False)
    if not matched_proc:
        return []

    logger.debug(f"Substituting CALL query '{query.name}' with procedure body")

    # Re-use find_arg logic. We don't have an Anonymous node,
    # just a list of args from the CallQuery.
    param_map = {}
    positional_map = {}
    args = query.args

    for i, param in enumerate(matched_proc.parameters):
        arg_expr = find_arg(args, param, i) or param.default

        if arg_expr:
            param_map[param.name.lower()] = arg_expr
            positional_map[str(i + 1)] = arg_expr

    replacement_exprs = []
    for stmt in matched_proc.inner_statements:
        # Procedures can contain multiple statements
        replacement_exprs.append(substitute_parameters(stmt.copy(), None, param_map, positional_map))

    logger.debug(f"Substituted to {len(replacement_exprs)} statements:")
    for r in replacement_exprs:
        logger.debug(f"  {r.sql(dialect=query.dialect)}")
    return replacement_exprs


def substitute_execute_with_plan(
    execute_name: str, execute_arguments: t.List[exp.Literal], object_mapping: mappings.ObjectMapping
) -> t.List[exp.Expr]:
    """
    Example:
        PREPARE stmt AS SELECT 1;
        EXECUTE stmt;
        ->
        SELECT 1;
    """
    plan_table = exp.to_table(execute_name)
    matched_prepare = object_mapping.lookup_prepare_query(plan_table, raise_on_missing=False)

    if not matched_prepare:
        raise exception.MappingError(message=f"Could not find PREPARE statement for plan: {execute_name}")

    expected = matched_prepare.parameter_count
    actual = len(execute_arguments)
    if expected > 0 and actual != expected:
        raise exception.MappingError(
            message=f"Wrong number of parameters for prepared statement (expected: {expected}, actual: {actual})"
        )

    logger.debug(f"Substituting EXECUTE query for plan '{execute_name}'")

    positional_map = {str(i + 1): arg for i, arg in enumerate(execute_arguments)}
    result_expr = substitute_parameters(matched_prepare.statement.copy(), None, {}, positional_map)

    return [result_expr]


def substitute_execute(query: ExecuteQuery) -> t.List[exp.Expr]:
    """
    Substitutes an EXECUTE statement with the statement of the PREPARE it refers to.

    Example:
        PREPARE stmt AS SELECT 1;
        EXECUTE stmt;
        ->
        SELECT 1;
    """
    execute_name = query.parameters.name
    execute_args = query.parameters.arguments

    return substitute_execute_with_plan(execute_name, execute_args, query.object_mapping)


def substitute_create_execute(query: CTASQuery) -> exp.Expr:
    """
    Substitutes 'EXECUTE <plan>' in 'CREATE TABLE AS' with the actual query.

    Example:
        PREPARE stmt AS SELECT 1 AS one;
        CREATE TABLE t AS EXECUTE stmt;
        ->
        CREATE TABLE t AS SELECT 1 AS one;
    """
    if exec_prop := query.statement.find(exp.ExecuteAsProperty):
        if isinstance(exec_prop.this, exp.Anonymous):
            execute_name = exec_prop.this.this
            execute_args = exec_prop.this.expressions
        else:
            execute_name = exec_prop.this.name
            execute_args = []

        result_expr = substitute_execute_with_plan(execute_name, execute_args, query.object_mapping)[0]

        # Replace property with the actual expression
        expression = query.statement
        expression.set("expression", result_expr)
        exec_prop.pop()

    return expression


def substitute_session_variables(
    stmt: exp.Expr,
    session_variables: dict[str, exp.Expr],
) -> exp.Expr:
    """
    Replaces $var Parameter nodes with their stored session variable values,
    and resolves IDENTIFIER($var) DynamicIdentifier nodes to concrete identifiers.
    """
    # 1. Walk and replace exp.Parameter nodes
    for node in stmt.walk():
        if isinstance(node, exp.Parameter):
            var_name = node.this.name.upper()
            if var_name in session_variables:
                logger.debug(f"Substituting session variable: ${var_name}")
                node.replace(session_variables[var_name].copy())

    # 2. Resolve any remaining DynamicIdentifier nodes that wrap a resolved Literal
    #    (e.g. IDENTIFIER('my_table') or IDENTIFIER($var) after step 1)
    #    Use transform to handle replacements more robustly during traversal
    def _transform_dynamic_identifiers(node):
        if isinstance(node, exp.DynamicIdentifier):
            inner = node.this
            if isinstance(inner, exp.Literal) and inner.is_string:
                resolved_name = inner.this

                if isinstance(node.parent, exp.Table):
                    # FROM IDENTIFIER($b) → FROM my_table
                    # Here we modify the parent Table node's 'this' arg
                    node.parent.set("this", exp.to_identifier(resolved_name.upper()))
                    return node  # It's already disconnected or about to be ignored
                else:
                    # SELECT IDENTIFIER($col) → SELECT col_name
                    return exp.column(resolved_name.upper())
        return node

    stmt.transform(_transform_dynamic_identifiers, copy=False)

    return stmt
