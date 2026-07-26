import logging
import typing as t

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types

from sqlleaf import mappings, util
from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import CallQuery, ExecuteQuery, Q, UserDefinedFunctionQuery, CTASQuery
from sqlleaf.processors.transformers import substitute
from sqlleaf.typing import E

logger = logging.getLogger("sqlleaf")


def lookup_udf_call(
    node: exp.Anonymous, object_mapping: mappings.ObjectMapping
) -> t.Optional[UserDefinedFunctionQuery]:
    """
    Looks up the UDF definition for a single exp.Anonymous node.
    Returns the matched UDF definition, or None if not found.
    """
    function_schema, function_name = util.get_udf_name(node)
    udf_object = exp.table_(table=function_name, db=function_schema)
    candidates = object_mapping.lookup_udf_query(table=udf_object, raise_on_missing=False)
    if not candidates:
        return None
    return mappings.resolve_overloaded_function(node, candidates)


def find_next_udf_call(
    expression: exp.Expr, object_mapping: mappings.ObjectMapping
) -> t.Tuple[t.Optional[exp.Anonymous], t.Optional[UserDefinedFunctionQuery]]:
    """
    Searches the AST for the next UDF call that matches any of the provided UDF definitions.
    Returns the call node and the matched UDF definition.
    """
    for node in expression.find_all(exp.Anonymous):
        best_match = lookup_udf_call(node, object_mapping)
        if best_match:
            return node, best_match

    return None, None


def transform_row_to_subquery(
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


def _get_alias(node: exp.Expr) -> t.Optional[str]:
    """Helper to extract an alias from a node or its parent."""
    alias = node.alias
    if not alias:
        if isinstance(node.parent, exp.Table):
            alias = node.parent.alias
        elif isinstance(node.parent, exp.Lateral):
            alias = node.parent.alias

    if not alias and hasattr(node, "this"):
        alias = node.this

    return alias


def create_subquery_with_alias(
    replacement_expr: exp.Expr, query: UserDefinedFunctionQuery, alias: str = "t"
) -> exp.Subquery:
    """Creates a Subquery with a table alias and the UDF's return columns."""
    if not alias:
        alias = "t"

    return exp.Subquery(
        this=replacement_expr,
        alias=exp.TableAlias(
            this=exp.Identifier(this=alias, quoted=False),
            columns=[c.this if isinstance(c, exp.ColumnDef) else exp.to_identifier(c) for c in query.return_columns],
        ),
    )


def create_lateral_replacement(
    target_node: exp.Expr, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery, alias: str = None
) -> None:
    """
    Wraps a replacement expression for use in a LATERAL context and applies it.

    Example:
        Before: `SELECT * FROM table1, LATERAL hello()`
        After: `SELECT * FROM table1, LATERAL (SELECT * FROM (SELECT ...) AS hello(name, age))`
        where hello() returns (name, age)
    """
    if query.return_columns:
        if not alias:
            alias = _get_alias(target_node) or "t"

        # Reconstruct the desired structure manually to avoid sqlglot's select().from_() overhead
        subquery_replacement = create_subquery_with_alias(replacement_expr, query, alias=alias)
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


def transform_udf_to_subquery_if_table_reference(
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
        replacement_expr = create_subquery_with_alias(replacement_expr, query, alias=alias)
    else:
        if isinstance(replacement_expr, (exp.Select, exp.Values)):
            replacement_expr = exp.Paren(this=replacement_expr)

    if isinstance(node.parent, exp.Lateral):
        create_lateral_replacement(node, replacement_expr, query, alias=alias)
    else:
        node.parent.replace(replacement_expr)


def get_dot_node(target_node: exp.Expr) -> t.Optional[exp.Dot]:
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


def transform_field_access_to_subquery(
    dot_node: exp.Dot, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery
) -> None:
    """
    Transforms a UDF with a field access into a subquery with the field selected.

    Example:
        Before: `(hello('John')).name`
        After: `(SELECT name FROM (SELECT 'John', 50) AS hello(name, age))`

    This is necessary because SQL doesn't allow direct field access on a subquery/UDF call
    without treating it as a table source or using a subquery. Returning a Subquery
    ensures the field access is correctly scoped and valid SQL.
    """
    field_name = dot_node.expression.name
    alias = _get_alias(dot_node.this) or "t"
    subquery = exp.select(field_name).from_(create_subquery_with_alias(replacement_expr, query, alias=alias))
    dot_node.replace(exp.Paren(this=subquery))


def replace_scalar_call(target_node: exp.Expr, replacement_expr: exp.Expr) -> None:
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


def get_target_node(node: exp.Anonymous) -> exp.Expr:
    """
    Returns the node to be replaced.
    """
    parent = node.parent
    # Qualified with a schema (e.g., myschema.myfunc())
    if isinstance(parent, exp.Dot) and isinstance(parent.left, exp.Identifier):
        return parent
    return node


def resolve_returning_to_select(
    stmt: exp.Expr,
    param_map: t.Dict[str, exp.Expr],
    query: UserDefinedFunctionQuery,
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Select:
    """
    Given a statement with a RETURNING clause (INSERT, UPDATE, DELETE, MERGE),
    resolves each RETURNING expression (handling parameter substitution
    and column-to-literal mapping for INSERT) and returns a SELECT expression.

    Example:
        INSERT INTO people (age) VALUES (5) RETURNING age
        → SELECT 5
    """
    returning_node = stmt.args.get("returning")
    if not returning_node:
        return exp.select("*")

    if isinstance(stmt, exp.Insert) and isinstance(stmt.expression, exp.Values):
        column_names = [c.name for c in stmt.this.expressions] if isinstance(stmt.this, exp.Schema) else None
        select_expr = util.convert_values_to_select(stmt.expression, query.dialect, column_names)

        # Create a SELECT that projects the RETURNING columns from the converted VALUES
        returning_select = exp.select(*returning_node.expressions).from_(select_expr.subquery("t"))
        return substitute.substitute_parameters(returning_select, query, param_map, positional_map)

    col_to_val = {}
    if isinstance(stmt, exp.Insert):
        # Extract insert columns. If 'this' is a Schema, it has expressions (columns)
        schema = stmt.this
        insert_cols = []
        if isinstance(schema, exp.Schema):
            insert_cols = [c.name for c in schema.expressions]

        values_node = stmt.find(exp.Values)
        values_literals = []
        if values_node and values_node.expressions:
            # Get the first row of values
            values_literals = values_node.expressions[0].expressions

        col_to_val = dict(zip(insert_cols, values_literals))

    resolved = []
    for ret_col in returning_node.expressions:
        col_name = ret_col.name if isinstance(ret_col, exp.Column) else ret_col.alias_or_name
        resolved_val = col_to_val.get(col_name, ret_col).copy()
        # Apply parameter substitution on the resolved value
        resolved_val = substitute.substitute_parameters(resolved_val, query, param_map, positional_map)
        resolved.append(resolved_val)

    return exp.select(*resolved)


def transform_inner_query(
    stmt: exp.Expr,
    param_map: t.Dict[str, exp.Expr],
    query: UserDefinedFunctionQuery,
    positional_map: t.Dict[str, exp.Expr],
) -> exp.Expr:
    """
    Performs replacement and transformations over a UDF's inner query.
    """
    # handle INSERT/UPDATE/DELETE/MERGE ... RETURNING inside a UDF body
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge)) and stmt.args.get("returning"):
        return resolve_returning_to_select(stmt, param_map, query, positional_map)

    if isinstance(stmt, exp.Values):
        stmt = util.convert_values_to_select(stmt, query.dialect)

    logger.debug(f"Transforming inner query: {stmt.sql()}")
    replacement_expr = substitute.substitute_parameters(stmt, query, param_map, positional_map)
    logger.debug(f"Query after parameter substitution: {replacement_expr.sql()}")

    # Handle ROW(...)::table_name replacement (composite/table type casting)
    replacement_expr = transform_row_function_to_subquery(replacement_expr, query)

    new_expr = replacement_expr
    return new_expr


def transform_row_function_to_subquery(replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> exp.Expr:
    """Transform a ROW() function into a subquery."""
    transformed = False

    for subnode in replacement_expr.walk():
        if isinstance(subnode, exp.Cast):
            row_expr = subnode.this
            if isinstance(row_expr, exp.Anonymous) and row_expr.this.lower() == "row":
                # Don't replace if it's being used for field access, as it's likely
                # already been handled or needs to be preserved.
                if not isinstance(subnode.parent, exp.Paren) or not isinstance(subnode.parent.parent, exp.Dot):
                    if subnode is not replacement_expr:
                        new_expr = transform_row_to_subquery(subnode, replacement_expr, query)
                        if new_expr:
                            transformed = True
                            replacement_expr = new_expr
    if transformed:
        logger.debug(f"Replaced ROW() to subquery: {replacement_expr.sql(dialect='postgres')}")
    return replacement_expr


def build_replacement_exprs(node: exp.Anonymous, query: UserDefinedFunctionQuery) -> t.List[exp.Expr]:
    """Builds the expressions that will replace a UDF call."""
    if query.return_type and query.return_type.this == exp.DataType.Type.NULL:
        return [exp.select(exp.Null())]

    param_map, positional_map = substitute.transform_arguments(node, query)

    replacement_exprs = []
    # Collect all child queries from the holder
    for child in query.holder.child_holders:
        stmt = child.original.statement

        if isinstance(stmt, (exp.Insert, exp.Update)) and not stmt.args.get("returning"):
            stmt = stmt.expression

        stmt = util.copy_expression(stmt)
        replacement_exprs.append(transform_inner_query(stmt, param_map, query, positional_map))

    return replacement_exprs


def apply_replacement(target_node: exp.Expr, replacement_expr: exp.Expr, query: UserDefinedFunctionQuery) -> None:
    """Applies the replacement of a UDF call node with its body logic."""
    logger.debug(f"Applying replacement for UDF: {query.name}")
    dot_node = get_dot_node(target_node)

    if isinstance(target_node.parent, exp.Lateral):
        logger.debug("Applying LATERAL replacement")
        alias = _get_alias(target_node) or "t"
        create_lateral_replacement(target_node, replacement_expr, query, alias=alias)
    elif isinstance(target_node.parent, exp.Table):
        logger.debug("Applying Table reference replacement")
        transform_udf_to_subquery_if_table_reference(target_node, replacement_expr, query)
    elif bool(query.return_columns and dot_node):  # A field
        logger.debug(f"Applying Field access replacement for field: {dot_node.expression.name}")
        transform_field_access_to_subquery(dot_node, replacement_expr, query)
    else:
        logger.debug("Applying Scalar call replacement")
        replace_scalar_call(target_node, replacement_expr)


def substitute_udf(statement: E, query: Q) -> t.List[exp.Expr]:
    """
    Inlines UDF calls in a SQL string with their defined bodies and parameters.
    Example:
        substitute_udf("SELECT hello('world')", [hello_udf])
        -> ["SELECT (SELECT 'Hello ' || 'world')"]

    Circular references in UDF/procedure definitions could cause infinite recursion.
    """
    result = []
    while True:
        # Annotate types to help with function overloading resolution
        expression = annotate_types(statement, dialect=query.dialect, schema=query.object_mapping)

        # Find the next UDF call to substitute
        to_replace, matched_udf = find_next_udf_call(expression, query.object_mapping)
        if not to_replace:
            break

        logger.debug(f"Found UDF call to substitute: {matched_udf.name}")

        param_map, _ = substitute.transform_arguments(to_replace, matched_udf)
        result = [expression]

        target_node = get_target_node(to_replace)
        replacement_exprs = build_replacement_exprs(to_replace, matched_udf)

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
                        apply_replacement(n, repl_expr, matched_udf)
                        break

                # Apply the substitution recursively.
                substituted_branches = substitute_udf(new_expression, query)
                if not substituted_branches:
                    final_results.append(new_expression)
                else:
                    final_results.extend(substituted_branches)
            return final_results

        # Single statement: apply replacement and continue finding next UDF calls
        apply_replacement(target_node, replacement_exprs[0], matched_udf)

    return result


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
        arg_expr = substitute.find_arg(args, param, i) or param.default

        if arg_expr:
            param_map[param.name.lower()] = arg_expr
            positional_map[str(i + 1)] = arg_expr

    replacement_exprs = []
    for stmt in matched_proc.inner_statements:
        # Procedures can contain multiple statements
        replacement_exprs.append(substitute.substitute_parameters(stmt.copy(), None, param_map, positional_map))

    logger.debug(f"Substituted to {len(replacement_exprs)} statements:")
    for r in replacement_exprs:
        logger.debug(f"  {r.sql(dialect=query.dialect)}")
    return replacement_exprs


def substitute_execute_with_plan(execute_name: str, execute_arguments: t.List[exp.Literal], object_mapping: mappings.ObjectMapping) -> t.List[exp.Expr]:
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
        raise SqlLeafException(message=f"Could not find PREPARE statement for plan: {execute_name}")

    expected = matched_prepare.parameter_count
    actual = len(execute_arguments)
    if expected > 0 and actual != expected:
        raise SqlLeafException(
            message=f"Wrong number of parameters for prepared statement (expected: {expected}, actual: {actual})"
        )

    logger.debug(f"Substituting EXECUTE query for plan '{execute_name}'")

    positional_map = {str(i + 1): arg for i, arg in enumerate(execute_arguments)}
    result_expr = substitute.substitute_parameters(matched_prepare.statement.copy(), None, {}, positional_map)

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
