from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.models.query import Q
from sqlleaf.typing import E, SqlObjectType
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
    while True:
        values = _pick_next_values_node(expr, unresolved_ids)
        if values is None:
            break

        # Determine if there is a CTE ancestor within the current statement scope
        cte = _cte_ancestor_in_scope(expr, values)
        if cte is not None:
            unresolved_ids.add(id(values))
            continue

        # VALUES is directly the expression of an INSERT
        parent = values.parent
        if isinstance(parent, exp.Insert) and parent.expression is values:
            new_stmt = _handle_values_in_insert(values, parent, parent is expr, query)
            if new_stmt is not None:
                expr = new_stmt
            continue

        # VALUES is directly the expression of a CREATE ... AS
        if isinstance(parent, exp.Create) and parent.expression is values:
            _handle_values_in_create(values, parent, query)
            continue

        # VALUES in a table position (wrapped by Subquery or direct FROM on SELECT/UPDATE)
        from_ancestor = values.find_ancestor(exp.From)
        if (
            values.find_ancestor(exp.Subquery) is not None
            or values.parent_select
            or (from_ancestor is not None and from_ancestor.this is values)
        ):
            _rewrite_values_in_table_position(values, query.dialect)
            continue

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


def _handle_values_in_create(
    values: exp.Values,
    parent: exp.Create,
    query: Q,
) -> None:
    """
    Handle VALUES directly under a CREATE ... AS expression.
    """
    _rewrite_values_statement(query, values, parent)


def _rewrite_values_in_table_position(values: exp.Values, dialect: str) -> None:
    """
    Rewrite VALUES used in FROM/JOIN/LATERAL positions.

    Supports both:
    - Subquery(Values), which updates the inner expression and preserves the outer alias/columns.
    - Direct 'From(Values)', which converts and transfers aliases.
    """
    # SELECT (VALUES ...)
    outer_subquery = values.find_ancestor(exp.Subquery)
    if outer_subquery is not None and outer_subquery.this is values:
        converted = _values_to_select_expr(
            values=values,
            dialect=dialect,
        )
        if isinstance(converted, exp.Subquery):
            converted = converted.this  # unwrap nested Subquery
        outer_subquery.set("this", converted)
        return

    # SELECT/UPDATE/DELETE FROM (VALUES ...)
    # Case A: VALUES appears in a SELECT's FROM
    parent_select = values.parent_select
    from_ = parent_select and parent_select.args.get("from_")
    if from_ and from_.this is values:
        converted = _values_to_select_expr(
            values=values,
            dialect=dialect,
        )
        # Ensure we have a Subquery in FROM and preserve the alias/column names
        original_alias = values.args.get("alias")
        if original_alias and not converted.args.get("alias"):
            converted.set("alias", original_alias)
        from_.set("this", converted)
        return

    # Case B: VALUES appears directly under a FROM of non-SELECT (e.g., UPDATE ... FROM (VALUES ...))
    from_ancestor = values.find_ancestor(exp.From)
    if from_ancestor is not None and from_ancestor.this is values:
        converted = _values_to_select_expr(
            values=values,
            dialect=dialect,
        )
        original_alias = values.args.get("alias")
        if not isinstance(converted, exp.Subquery):
            converted = converted.subquery()
        if original_alias and not converted.args.get("alias"):
            converted.set("alias", original_alias)
        from_ancestor.set("this", converted)


def _resolve_values_column_names(values: exp.Values, container: exp.Expr, query: Q) -> list[str]:
    """
    Resolve column names for the expressions inside VALUES() based on its surrounding expressions.
    """
    columns = []
    if isinstance(container, exp.CTE):
        columns = container.alias_column_names
    elif not isinstance(container, exp.Values):
        columns = [e.name for e in container.this.expressions]

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


def _rewrite_values_statement(query: Q, expression: exp.Values, statement: E) -> E:
    """
    Convert a `VALUES(...)` statement into a `SELECT ... UNION ALL SELECT ...` statement
    and rewrite the parent statement in-place.
    """
    if not isinstance(expression, exp.Values):
        return statement

    columns = _resolve_values_column_names(expression, statement, query)

    # Determine target table for INSERT/CREATE rewriting where needed
    if query.target_info.type == SqlObjectType.TABLE:
        child_table = query.target_info.expression
    else:
        child_table = statement.this

    # Build the 'SELECT ... UNION ALL SELECT ...'
    new_statement = _values_to_select_expr(
        values=expression,
        dialect=query.dialect,
        column_names=columns,
    )

    # Rewrite the parent statement
    if isinstance(statement, exp.Insert):
        insert_expr = exp.insert(
            expression=new_statement,
            columns=statement.this.expressions,
            into=child_table,
            returning=statement.args.get("returning"),
        )
        insert_expr.set("conflict", statement.args.get("conflict"))
        statement.replace(insert_expr)
        statement = insert_expr
    elif isinstance(statement, exp.Create):
        expression.pop()
        statement.set("expression", new_statement)
    elif isinstance(statement, exp.CTE):
        expression.pop()
        statement.set("this", new_statement)
    elif isinstance(statement, exp.Values):
        statement = new_statement
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
