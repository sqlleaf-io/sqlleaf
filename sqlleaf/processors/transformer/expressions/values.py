from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf import exception, util
from sqlleaf.models.query import Q
from sqlleaf.typing import E
from sqlleaf.util import default_column_index_iterator

logger = logging.getLogger("sqlleaf")


def normalize_values(query: Q, expr: exp.Expr) -> exp.Expr:
    """
    Convert a VALUES() statement into a SELECT .. UNION statement.
    This handles two cases:
    - When it is a top-level query (e.g. INSERT .. VALUES, CTAS .. VALUES)
    - When it is inside another query, e.g. nested in an expression
    """
    if isinstance(expr, exp.Values):
        return _rewrite_values_statement(query, expression=expr, statement=expr)

    unresolved_ids: t.Set[int] = set()

    # Walk the subtree and rewrite all Values occurrences
    prev_value = None
    while True:
        values = _pick_next_values_node(expr, unresolved_ids)
        if values and prev_value == values:
            raise exception.SqlLeafException("Infinite loop detected while searching for the next VALUES() expression.")

        if values is None:
            break

        # Determine if there is a CTE ancestor within the current statement scope
        cte = _cte_ancestor_in_scope(expr, values)
        if cte is not None:
            if cte.this is values:
                _rewrite_values_statement(query, values, cte)
            else:
                unresolved_ids.add(id(values))
        else:
            # VALUES is directly the expression of an INSERT
            parent = values.parent
            if isinstance(parent, exp.Insert) and parent.expression is values:
                new_stmt = _handle_values_in_insert(values, parent, parent is expr, query)
                if new_stmt is not None:
                    expr = new_stmt

            # VALUES is directly the expression of a CREATE ... AS
            elif isinstance(parent, exp.Create) and parent.expression is values:
                _rewrite_values_statement(query, values, parent)

            # VALUES is one of the sides of a UNION
            elif isinstance(parent, exp.SetOperation):
                _rewrite_values_statement(query, values, parent)

            else:
                # VALUES in a table position (wrapped by Subquery or direct FROM on SELECT/UPDATE)
                from_ancestor = values.find_ancestor(exp.From)
                if (
                    values.find_ancestor(exp.Subquery) is not None
                    or values.parent_select
                    or (from_ancestor is not None and from_ancestor.this is values)
                ):
                    _rewrite_values_in_table_position(values, query.dialect)

        prev_value = values
    return expr


def _pick_next_values_node(statement: exp.Expr, unresolved: set[int]) -> exp.Values | None:
    """
    Return the next exp.Values node in the statement not present in `unresolved`.
    """
    for candidate in statement.find_all(exp.Values):
        if id(candidate) not in unresolved:
            return candidate
    return None


def _cte_ancestor_in_scope(statement: exp.Expr, values: exp.Values) -> exp.CTE | None:
    """
    Return the enclosing CTE only if it belongs to the current statement's subtree.
    This is to prevent us from using a CTE that does not enclose us.
    """
    cte = values.find_ancestor(exp.CTE)
    if cte is None:
        return None

    ctes_in_scope = {id(c) for c in statement.find_all(exp.CTE)}
    if id(cte) not in ctes_in_scope:
        return None

    return cte


def _handle_values_in_insert(
    values: exp.Values,
    parent: exp.Insert,
    is_top_level: bool,
    query: Q,
) -> t.Optional[exp.Expr]:
    """
    Handle VALUES directly under an INSERT expression.

    Returns a possibly updated top-level statement when the INSERT itself is
    replaced and it is the top-level statement.
    """
    converted = _rewrite_values_statement(query, values, parent)
    if isinstance(converted, exp.Insert) and is_top_level:
        return converted
    return None


def _rewrite_values_in_table_position(values: exp.Values, dialect: str) -> None:
    """
    Rewrite VALUES used in FROM/JOIN/LATERAL positions.

    Supports both:
    - Subquery(Values), which updates the inner expression and preserves the outer alias/columns.
    - Direct 'From(Values)', which converts and transfers aliases.
    """
    converted = _values_to_select_expr(
        values=values,
        dialect=dialect,
    )

    # SELECT (VALUES ...)
    outer_subquery = values.find_ancestor(exp.Subquery)
    if outer_subquery is not None and outer_subquery.this is values:
        if isinstance(converted, exp.Subquery):
            converted = converted.this  # unwrap nested Subquery
        outer_subquery.set("this", converted)
        return

    # SELECT/UPDATE/DELETE FROM (VALUES ...)
    # Case A: VALUES appears in a SELECT's FROM
    parent_select = values.parent_select
    from_ = parent_select and parent_select.args.get("from_")
    if from_ and from_.this is values:
        # Ensure we have a Subquery in FROM and preserve the alias/column names
        original_alias = values.args.get("alias")
        if original_alias and not converted.args.get("alias"):
            converted.set("alias", original_alias)
        from_.set("this", converted)
        return

    # Case B: VALUES appears directly under a FROM of non-SELECT (e.g., UPDATE ... FROM (VALUES ...))
    from_ancestor = values.find_ancestor(exp.From)
    if from_ancestor is not None and from_ancestor.this is values:
        original_alias = values.args.get("alias")
        if not isinstance(converted, exp.Subquery):
            converted = converted.subquery()
        if original_alias and not converted.args.get("alias"):
            converted.set("alias", original_alias)
        from_ancestor.set("this", converted)


def _resolve_values_column_names(values: exp.Values, parent: exp.Expr, query: Q) -> list[str]:
    """
    Resolve column names for the expressions inside VALUES() based on its surrounding expressions.
    """
    columns = []
    if isinstance(parent, exp.CTE):
        columns = parent.alias_column_names
    elif not isinstance(parent, exp.Values):
        columns = [e.name for e in parent.this.expressions]

    if not columns:
        # Fall back to the mapping
        # TODO: remove after downstream bug found
        child_table = query.target_info.expression
        if isinstance(child_table, exp.Table):
            cols = query.object_mapping.find_columns_for_table(child_table)
            values_lists: t.List[exp.Tuple] = values.expressions
            columns = list(cols)[: len(values_lists[0].expressions)]

    # Returning empty will populate dialect defaults
    return list(columns)


def _substitute_default_column_references(query: Q, values: exp.Values, target_table: exp.Table | None) -> None:
    """
    Replace the column names used inside `INSERT ... VALUES (...)` statements
    with the referenced column's DEFAULT expression (or NULL), per MySQL's semantics for
    VALUES(column_name).

    This also applies when the column reference is nested inside another expression,
    e.g. VALUES(UPPER(name), age * 2).

    Example [given name's default is 5]:
        INSERT INTO (name) VALUES (name)
    ->
        INSERT INTO (name) SELECT 5 AS name
    """
    if target_table is None:
        return

    table_query = query.object_mapping.lookup_table_query(table=target_table, raise_on_missing=False)
    if not table_query:
        return

    table_columns = table_query.get_column_defs()
    table_column_names = {col.name for col in table_columns}

    for value_expr in values.expressions:
        if not isinstance(value_expr, exp.Tuple):
            continue

        # Replace each column with its default/generated expression
        for tuple_expr in value_expr.expressions:
            for column_ref in list(tuple_expr.find_all(exp.Column)):
                if column_ref.name in table_column_names:
                    col_def = next(c for c in table_columns if c.name == column_ref.name)
                    if default_constraint := util.get_column_constraint_expression(col_def):
                        column_ref.replace(default_constraint.this.copy())
                    else:
                        column_ref.replace(exp.Null())


def _rewrite_empty_values_or_values_with_column_names(
    query: Q, expression: exp.Values, statement: E, columns: t.List[str]
) -> t.List[str]:
    """
    MySQL-only handling for INSERT ... VALUES lists:
    - Expand empty VALUES() to refer to all target columns so DEFAULTs can be applied.
    - Replace target column-name references in VALUES(...) with that column's DEFAULT (or NULL).

    Example:
      CREATE TABLE t(a INT DEFAULT 5, b INT);
      INSERT INTO t () VALUES();            -> SELECT 5 AS a, NULL AS b
      INSERT INTO t (a,b) VALUES(a, UPPER(b)) -> SELECT 5 AS a, UPPER(NULL) AS b
    """
    if isinstance(statement, exp.Insert) and query.dialect == "mysql":
        into_table = statement.find(exp.Table)

        # Expand an empty tuple to reference all target columns so substitution can occur
        if (
            expression.expressions
            and isinstance(expression.expressions[0], exp.Tuple)
            and len(expression.expressions[0].expressions) == 0
        ):
            table_query = (
                query.object_mapping.lookup_table_query(table=into_table, raise_on_missing=False)
                if into_table is not None
                else None
            )
            if table_query:
                # Replace the empty tuple values with references to each column name
                columns = [c.name for c in table_query.get_column_defs()]
                expression.expressions[0].set("expressions", [exp.column(c) for c in columns])

        _substitute_default_column_references(query, expression, into_table)

    return columns


def _rewrite_values_statement(query: Q, expression: exp.Values, statement: E) -> E:
    """
    Convert a `VALUES(...)` statement into a `SELECT ... UNION ALL SELECT ...` statement
    and rewrite the parent statement in-place.
    """
    if not isinstance(expression, exp.Values):
        return statement

    columns = _resolve_values_column_names(expression, statement, query)
    columns = _rewrite_empty_values_or_values_with_column_names(query, expression, statement, columns)

    # Build the 'SELECT ... UNION ALL SELECT ...'
    new_statement = _values_to_select_expr(
        values=expression,
        dialect=query.dialect,
        column_names=columns,
    )

    # Rewrite the parent statement with the existing column list
    if isinstance(statement, exp.Insert):
        into_table = statement.find(exp.Table)
        insert_columns = statement.this.expressions

        insert_expr = exp.insert(
            expression=new_statement,
            columns=insert_columns,
            into=into_table or statement.this,
            returning=statement.args.get("returning"),
        )
        insert_expr.set("conflict", statement.args.get("conflict"))
        statement.replace(insert_expr)
        statement = insert_expr
    elif isinstance(statement, exp.Create):
        expression.replace(new_statement)
    elif isinstance(statement, exp.CTE):
        if isinstance(new_statement, exp.Subquery):
            new_statement = new_statement.this
        expression.replace(new_statement)
    elif isinstance(statement, exp.Values):
        statement = new_statement
    elif isinstance(statement, exp.SetOperation):
        expression.replace(new_statement)
    else:
        raise exception.SqlLeafException(message=f"Unknown statement type: {statement.__class__}")

    return statement


def _values_to_select_expr(
    values: exp.Values,
    dialect: str,
    column_names: t.Optional[t.List[str]] = None,
) -> exp.Expr:
    """
    Convert an exp.Values into an exp.Select or exp.Union.
    """
    values_lists: t.List[exp.Tuple] = values.expressions
    if not column_names:
        column_names = list(default_column_index_iterator(dialect, values_lists[0].expressions))

    selects = []
    for val_list in values_lists:
        row_vals = val_list.expressions
        cols = [exp.alias_(val, str(col)) for col, val in zip(column_names, row_vals)]
        selects.append(cols)

    if len(selects) > 1:
        new_selects = [exp.select(*select) for select in selects]
        return_expr = exp.union(*new_selects, distinct=False)
    else:
        return_expr = exp.select(*selects[0])

    # Wrap the query in a subquery if it's not a top-level statement
    return return_expr.subquery() if values.parent_select else return_expr
