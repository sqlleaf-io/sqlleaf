import logging
import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query import UserDefinedFunctionQuery
from sqlleaf.processors.collector import substitute
from sqlleaf.processors.transformer.expressions import normalize_values
from sqlleaf.processors.transformer.expressions.row import transform_row_function_to_subquery

logger = logging.getLogger("sqlleaf")





def find_next_udf_call(
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


def create_subquery_with_alias(
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

    node.parent.replace(replacement_expr)


def replace_scalar_call(target_node: exp.Expr, replacement_expr: exp.Expr) -> None:
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

    Notes on INSERT ... VALUES ... RETURNING:
    - Even after the unified VALUES normalization pass (which converts VALUES →
      SELECT/UNION during preprocess for regular statements), UDF inner bodies are
      transformed here independently.
    - We intentionally resolve INSERT ... VALUES ... RETURNING by selecting the
      requested columns from the target table rather than from the VALUES-derived
      UNION. This preserves the semantics that RETURNING reflects the post-insert
      target-row shape and also avoids leaking the VALUES union into the generator.

    Example:
        INSERT INTO people (age) VALUES (5), (2) RETURNING age
        → SELECT people.age FROM people
    """
    returning_node = stmt.args.get("returning")
    if isinstance(stmt, exp.Insert) and isinstance(stmt.expression, exp.Values):
        # For INSERT ... VALUES ... RETURNING, select the RETURNING columns from the
        # target table. See the note in the docstring above for the rationale.
        table = stmt.this.this if isinstance(stmt.this, exp.Schema) else stmt.this
        returning_select = exp.select(*[r.copy() for r in returning_node.expressions]).from_(table.copy())
        return substitute.substitute_parameters(returning_select, query, param_map, positional_map)

    col_to_val = {}
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

    Example:
        Given a UDF body statement `SELECT $1 * 2 AS val` with param_map `{"$1": 5}`:
            → SELECT 5 * 2 AS val

        Given a UDF body statement `INSERT INTO people (age) VALUES (5) RETURNING age`:
            → SELECT people.age FROM people
    """
    # handle INSERT/UPDATE/DELETE/MERGE ... RETURNING inside a UDF body
    if isinstance(stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge)) and stmt.args.get("returning"):
        return resolve_returning_to_select(stmt, param_map, query, positional_map)

    if isinstance(stmt, exp.Values):
        stmt = normalize_values(query, stmt)

    logger.debug(f"Transforming inner query: {stmt.sql()}")
    replacement_expr = substitute.substitute_parameters(stmt, query, param_map, positional_map)
    logger.debug(f"Query after parameter substitution: {replacement_expr.sql()}")

    # Handle ROW(...)::table_name replacement (composite/table type casting)
    replacement_expr = transform_row_function_to_subquery(replacement_expr, query)

    new_expr = replacement_expr
    return new_expr


def build_replacement_exprs(node: exp.Anonymous, query: UserDefinedFunctionQuery) -> t.List[exp.Expr]:
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

    param_map, positional_map = substitute.transform_arguments(node, query)

    replacement_exprs = []
    # Collect all child queries from the holder
    for child in query.holder.downstream_holders:
        stmt = child.original.statement
        stmt = util.copy_expression(stmt)
        replacement_exprs.append(transform_inner_query(stmt, param_map, query, positional_map))

    return replacement_exprs


def substitute_udf(
    node: exp.Anonymous,
    query: UserDefinedFunctionQuery,
) -> t.List[exp.Expr]:
    """
    Returns the UDF's inner body with arguments substituted.
    Does NOT modify the caller query.
    Mirrors the contract of substitute_call / substitute_execute_with_plan.
    """
    return build_replacement_exprs(node, query)


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
        transform_udf_to_subquery_if_table_reference(target_node, replacement_expr, query)
    else:
        logger.debug("Applying Scalar call replacement")
        replace_scalar_call(target_node, replacement_expr)
