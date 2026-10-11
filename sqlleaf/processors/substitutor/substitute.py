import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.simplify import simplify

from sqlleaf import exception, mappings, util
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import (
    CallQuery,
    CTASQuery,
    ExecuteDynamicQuery,
    ExecuteQuery,
    FunctionParam,
    Q,
    UserDefinedFunctionQuery,
)
from sqlleaf.processors.transformer.expressions import normalize_values
from sqlleaf.processors.transformer.expressions.row import transform_row_function_to_subquery

logger = logging.getLogger("sqlleaf")


def _replace_session_parameter(
    node: exp.Expr,
    session_variables: dict[str, exp.Expr],
) -> exp.Expr:
    if isinstance(node, exp.Parameter) and isinstance(node.this, exp.Var):
        var_name = node.this.name.upper()
        value = session_variables.get(var_name)
        if value is not None:
            logger.debug(f"Substituting session variable: ${var_name}")
            return value.copy()
    return node


def _transform_dynamic_identifier(node: exp.Expr) -> exp.Expr:
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


def _build_param_maps(
    args: t.List[exp.Expr], params: t.List[FunctionParam]
) -> t.Tuple[t.Dict[str, exp.Expr], t.Dict[str, exp.Expr]]:
    """
    Builds the parameter and positional maps for a list of actual arguments against a list of declared parameters.

    Example:
        For parameters `(x, y)` called as `my_func(1, y => 2)`, returns:
        param_map = {"x": 1, "y": 2}
        positional_map = {"1": 1, "2": 2}
    """
    param_map = {}
    positional_map = {}

    for i, param in enumerate(params):
        arg_expr = _find_arg(args, param, i) or param.default

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


def transform_function_arguments(
    node: exp.Anonymous, query: UserDefinedFunctionQuery
) -> t.Tuple[t.Dict[str, exp.Expr], t.Dict[str, exp.Expr]]:
    """
    Transforms every argument passed to the UDF into the correct format.

    Example:
        For a UDF with parameters `(x, y)` called as `my_udf(1, y => 2)`, returns:
        param_map = {"x": 1, "y": 2}
        positional_map = {"1": 1, "2": 2}
    """
    logger.debug(f"Transforming arguments for UDF: {query.name}")
    return _build_param_maps(args=node.expressions, params=query.parameters)


def substitute_cursor_parameters(
    cursor_query: exp.Expr,
    call_args: t.List[exp.Expr],
    cursor_args: t.List[pgexp.PGCursorArg],
) -> exp.Expr:
    """
    Substitutes a cursor's declared parameters with the actual arguments passed to its OPEN call.

    Example:
        Cursor query: `SELECT UPPER(key) AS name`
        Declared parameters: `(key VARCHAR)`
        Call arguments: `('abc')`
        Result: `SELECT UPPER('abc') AS name`
    """
    params = [FunctionParam(name=arg.this.name, type=arg.args.get("kind")) for arg in cursor_args]
    param_map, positional_map = _build_param_maps(args=call_args, params=params)
    return substitute_parameters(cursor_query, None, param_map, positional_map)


def substitute_parameters(
    expr: exp.Expr,
    query: UserDefinedFunctionQuery,
    param_map: t.Dict[str, exp.Expr],
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Expr:
    """
    Replaces parameter references within an expression and its child expressions with their corresponding arguments.

    Example:
        Expression: `SELECT $1 + x`
        Maps: param_map={'x': 10}, positional_map={'1': 5}
        Result: `SELECT 5 + 10`
    """
    # 1. Handle case where the root replacement expression itself needs substitution (e.g., expression is just 'x')
    if isinstance(expr, exp.Column) and not expr.table:
        col_name = expr.this.name.lower()
        if col_name in param_map:
            return param_map[col_name].copy()

    elif isinstance(expr, exp.Parameter):
        param_id = expr.this.name
        if param_id in positional_map:
            return positional_map[param_id].copy()

    # 2. Walk and replace all references in the expression tree
    for subnode in expr.walk():
        _substitute_parameter_node(subnode, query, param_map, positional_map)

    return expr


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
    Substitutes a CALL statement's arguments into the statmenets inside its body and returns them.
    Circular references in procedure-to-procedure calls could cause infinite recursion.

    Example:
        CREATE PROCEDURE hello() ... SELECT 3;
        CALL hello();
        ->
        SELECT 3;
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
        arg_expr = _find_arg(args, param, i) or param.default

        if arg_expr:
            param_map[param.name.lower()] = arg_expr
            positional_map[str(i + 1)] = arg_expr

    replacement_exprs = []
    for stmt in matched_proc.inner_statements:
        # Procedures can contain multiple statements
        new_stmt = substitute_parameters(stmt.copy(), None, param_map, positional_map)
        replacement_exprs.append(new_stmt)

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


def resolve_dynamic_sql_command(
    command: exp.Expr | None,
    using: t.List[exp.Expr],
    object_mapping: mappings.ObjectMapping,
    dialect: str,
    error_statement: exp.Expr,
) -> exp.Expr | None:
    """
    Resolve the query inside an 'EXECUTE <command-string> [USING ...]' query.
    """
    logger.debug(f"Resolving dynamic SQL command: {command}")
    if isinstance(command, exp.Literal):
        resolved_command = command
    elif isinstance(command, exp.Column):
        resolved_command = object_mapping.get_variable(name=command.name)
        if not isinstance(resolved_command, exp.Literal):
            exception.raise_error(
                exception.UnsupportedFeatureError,
                f"Dynamic EXECUTE with a variable of type {type(command)} is not supported yet: "
                f"{error_statement.sql(dialect=dialect)}",
            )
            return None
    elif isinstance(command, exp.DPipe):
        resolved_command = simplify(command, dialect="postgres")
    else:
        exception.raise_error(
            exception.UnsupportedFeatureError,
            f"Dynamic EXECUTE with a command string of type {type(command)} is not supported yet: "
            f"{error_statement.sql(dialect=dialect)}",
        )
        return None

    resolved_stmt = sqlglot.parse_one(resolved_command.this, dialect=dialect)
    if using:
        resolved_using = object_mapping.get_variables_for(expressions=using)
        if resolved_using:
            positional_map = {str(i + 1): value for i, value in enumerate(resolved_using)}
            resolved_stmt = substitute_parameters(resolved_stmt, None, {}, positional_map)
    return resolved_stmt


def substitute_execute_dynamic(query: ExecuteDynamicQuery) -> t.List[exp.Expr]:
    """
    Parse the dynamic command string of an EXECUTE statement in PL/pgSQL and substitute its
    positional parameters ($1, $2, ...) with the resolved USING arguments.

    Example:
        DECLARE my_name varchar := 'there';
        EXECUTE 'INSERT INTO target (name) SELECT $1' USING my_name;
        ->
        INSERT INTO target (name) SELECT 'there'
    """
    resolved = resolve_dynamic_sql_command(
        command=query.command,
        using=query.using,
        object_mapping=query.object_mapping,
        dialect=query.dialect,
        error_statement=query.statement,
    )
    return [resolved] if resolved is not None else []


def substitute_ctas_execute(query: CTASQuery) -> exp.Create:
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
    # Replace exp.Parameter nodes recursively.
    # This ensures nested variables are fully resolved, e.g., $b where b = $a + 1
    # and a = 1 should become 1 + 1 after two passes.
    replace_parameter = lambda node: _replace_session_parameter(node, session_variables)

    # Guard against cycles (e.g. SET a = $b; SET b = $a) by tracking seen AST states.
    seen_states: set[str] = set()
    while True:
        state = repr(stmt.dump())
        if state in seen_states:
            break
        seen_states.add(state)

        stmt = stmt.transform(replace_parameter, copy=False)
        if repr(stmt.dump()) == state:
            break

    # Resolve any remaining DynamicIdentifier nodes that wrap a resolved Literal
    # (e.g. IDENTIFIER('my_table') or IDENTIFIER($var)
    stmt.transform(_transform_dynamic_identifier, copy=False)

    return stmt


def _substitute_udf(node: exp.Anonymous, query: UserDefinedFunctionQuery) -> t.List[exp.Expr]:
    """
    Builds the expressions that will replace a UDF call.

    Example:
        Given a UDF `hello()` defined as `SELECT 'Hello'` and a call site `hello()`:
            → [SELECT 'Greetings!' AS greeting]

        Given a UDF `hello()` with a RETURNING body `INSERT INTO people (age) VALUES (5) RETURNING age`:
            → [SELECT people.age FROM people]
    """
    if query.return_type and query.return_type.this == exp.DataType.Type.NULL:
        return [exp.select(exp.Null())]

    param_map, positional_map = transform_function_arguments(node, query)

    replacement_exprs = []
    for stmt in query.inner_statements:
        stmt = util.copy_expression(stmt)
        replacement_exprs.append(_transform_inner_query(stmt, param_map, query, positional_map))

    return replacement_exprs


def substitute_udf(query: Q) -> t.Generator[tuple[exp.Expr, str]]:
    """
    Substitute UDFs in-place for an expression.

    For example,
    """
    while True:
        node, matched_udf = _find_next_udf_call(query.statement, query.object_mapping)
        if not node:
            break

        # Check for any DML inner statements (e.g. INSERT ... VALUES ... RETURNING)
        raw_inner = matched_udf.inner_statements
        param_map, positional_map = transform_function_arguments(node, matched_udf)
        parent_index = query.get_statement_index()
        for idx, raw_stmt in enumerate(raw_inner):
            if isinstance(raw_stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge)) and raw_stmt.args.get("returning"):
                subst_expr = substitute_parameters(raw_stmt.copy(), matched_udf, param_map, positional_map)
                yield subst_expr, f"{parent_index}:{idx}"

        target_node = _get_target_node(node)
        replacement_exprs = _substitute_udf(node, matched_udf)
        if not replacement_exprs:
            break

        if len(replacement_exprs) > 1:
            apply_replacement(target_node, replacement_exprs[-1], matched_udf)
        else:
            apply_replacement(target_node, replacement_exprs[0], matched_udf)


def _find_next_udf_call(
    expression: exp.Expr, object_mapping: mappings.ObjectMapping
) -> t.Tuple[t.Optional[exp.Anonymous], t.Optional[UserDefinedFunctionQuery]]:
    """
    Searches the AST for the next UDF call that matches any of the provided UDF definitions.
    Returns the call node and the matched UDF definition.
    """
    for node in expression.find_all(exp.Anonymous):
        best_match = object_mapping.lookup_udf_call(node)
        if best_match:
            return node, best_match

    return None, None


def _get_alias(node: exp.Expr) -> t.Optional[str]:
    """Helper to extract an alias from a node or its parent."""
    alias = node.alias
    if not alias:
        if isinstance(node.parent, exp.Table):
            alias = node.parent.alias

    if not alias and hasattr(node, "this"):
        alias = node.this

    return alias


def _create_subquery_with_alias(
    replacement_expr: exp.Expr, query: UserDefinedFunctionQuery, alias: str = "t"
) -> exp.Subquery:
    """Creates a Subquery with a table alias and the UDF's return columns."""
    return exp.Subquery(
        this=replacement_expr,
        alias=exp.TableAlias(
            this=exp.Identifier(this=alias, quoted=False),
            columns=[c.this if isinstance(c, exp.ColumnDef) else exp.to_identifier(c) for c in query.return_columns],
        ),
    )


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
        alias = _get_alias(node) or "t"
        replacement_expr = _create_subquery_with_alias(replacement_expr, query, alias=alias)

    node.parent.replace(replacement_expr)


def _replace_scalar_call(target_node: exp.Expr, replacement_expr: exp.Expr) -> None:
    """
    Replaces a scalar UDF call, wrapping query-like expressions in a Subquery.

    Example:
        Given hello() as `SELECT 1`,
        Before: `SELECT hello()`
        After: `SELECT (SELECT 1)`
    """
    if isinstance(replacement_expr, (exp.Select, exp.Values)):
        replacement_expr = exp.Subquery(this=replacement_expr)
    copied = replacement_expr.copy()
    target_node.replace(copied)


def _get_target_node(node: exp.Anonymous) -> exp.Expr:
    """
    Returns the node to be replaced.
    """
    parent = node.parent
    # Qualified with a schema (e.g., myschema.myfunc())
    if isinstance(parent, exp.Dot) and isinstance(parent.left, exp.Identifier):
        return parent
    return node


def _resolve_returning_to_select(
    stmt: exp.Expr,
    param_map: t.Dict[str, exp.Expr],
    query: UserDefinedFunctionQuery,
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Select:
    """
    Given a statement with a RETURNING clause (INSERT, UPDATE, DELETE, MERGE),
    resolve each RETURNING expression and return a SELECT expression.

    Notes on INSERT ... VALUES ... RETURNING:
    - We intentionally resolve INSERT ... VALUES ... RETURNING by selecting the
      requested columns from the target table rather than from the VALUES-derived
      UNION. This preserves the semantics that RETURNING reflects the post-insert
      target-row value.

    Example:
        INSERT INTO people (age) VALUES (5), (2) RETURNING age
        → SELECT people.age FROM people
    """
    returning_node = stmt.args.get("returning")
    if isinstance(stmt, exp.Insert) and isinstance(stmt.expression, exp.Values):
        # TODO: this shouldn't be the select expr, but just direct lineage from the target column to the returning column
        # For INSERT ... VALUES ... RETURNING, select the RETURNING columns from the target table.
        table = stmt.find(exp.Table)
        returning_select = exp.select(*[r.copy() for r in returning_node.expressions]).from_(table.copy())
        return substitute_parameters(returning_select, query, param_map, positional_map)

    col_to_val = {}
    resolved = []
    for ret_col in returning_node.expressions:
        col_name = ret_col.name if isinstance(ret_col, exp.Column) else ret_col.alias_or_name
        resolved_val = col_to_val.get(col_name, ret_col).copy()
        # Apply parameter substitution on the resolved value
        resolved_val = substitute_parameters(resolved_val, query, param_map, positional_map)
        resolved.append(resolved_val)

    return exp.select(*resolved)


def _transform_inner_query(
    stmt: exp.Expr,
    param_map: t.Dict[str, exp.Expr],
    query: UserDefinedFunctionQuery,
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Expr:
    """
    Performs replacement and transformations over a UDF's inner query.

    Example:
        Given a UDF body statement `SELECT $1 * 2 AS val` with param_map `{"$1": 5}`:
            → SELECT 5 * 2 AS val

        Given a UDF body statement `INSERT INTO people (age) VALUES (5) RETURNING age`:
            → SELECT people.age FROM people
    """
    # handle INSERT/UPDATE/DELETE/MERGE ... RETURNING inside a UDF body
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge)) and stmt.args.get("returning"):
        return _resolve_returning_to_select(stmt, param_map, query, positional_map)

    if isinstance(stmt, exp.Values):
        stmt = normalize_values(query, stmt)

    logger.debug(f"Transforming inner query: {stmt.sql()}")
    replacement_expr = substitute_parameters(stmt, query, param_map, positional_map)
    logger.debug(f"Query after parameter substitution: {replacement_expr.sql()}")

    # Handle ROW(...)::table_name replacement (composite/table type casting)
    replacement_expr = transform_row_function_to_subquery(replacement_expr, query)

    new_expr = replacement_expr
    return new_expr


def apply_replacement(target_node: exp.Expr, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> None:
    """
    Applies the replacement of a UDF call node with its body logic.

    Dispatches to the appropriate replacement strategy based on the call context:
    - LATERAL context: wraps the replacement in a LATERAL subquery.
    - Table reference context: wraps the replacement as a derived table.
    - Field access (dot notation): replaces with a field-access subquery.
    - Scalar call: replaces the call node inline.

    Example:
        Given `SELECT hello()` where `hello()` resolves to `SELECT 'Greetings!' AS greeting`:
            → SELECT (SELECT 'Greetings!' AS greeting) AS hello
    """
    logger.debug(f"Applying replacement for UDF: {query.name}")

    if isinstance(target_node.parent, exp.Table):
        logger.debug("Applying Table reference replacement")
        _transform_udf_to_subquery_if_table_reference(target_node, replacement_expr, query)
    else:
        logger.debug("Applying Scalar call replacement")
        _replace_scalar_call(target_node, replacement_expr)
