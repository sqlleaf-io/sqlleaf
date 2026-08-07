from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.models.query import Q
from sqlleaf.typing import E
from sqlleaf.util import default_column_index_iterator


def normalize_all_values(query, statement: E) -> E:
    """
    Converts VALUES() expressions into SELECT/UNION ALL expressions.
    """
    unresolved_ids: t.Set[int] = set()

    while True:
        # Pick the next actionable VALUES node
        values = _pick_next_values_node(statement, unresolved_ids)
        if values is None:
            break

        # Determine if there is a CTE ancestor within the current statement scope
        cte = _cte_ancestor_in_scope(statement, values)

        # Case 1: VALUES is nested inside a writable CTE – defer to inner-CTE flow
        if cte is not None:
            unresolved_ids.add(id(values))
            continue

        # Case 2: VALUES is directly the expression of an INSERT
        parent = values.parent
        if isinstance(parent, exp.Insert) and parent.expression is values:
            new_stmt = _handle_values_in_insert(values, parent, parent is statement, query)
            if new_stmt is not None:
                statement = new_stmt
            continue

        # Case 3: VALUES is directly the expression of a CREATE ... AS
        if isinstance(parent, exp.Create) and parent.expression is values:
            _handle_values_in_create(values, parent, query)
            continue

        # Case 4 & 5: VALUES in a table position (wrapped by Subquery or direct FROM)
        if values.find_ancestor(exp.Subquery) is not None or values.parent_select:
            _rewrite_values_in_table_position(values, query.dialect)
            continue

        # Otherwise: leave untouched for now
        unresolved_ids.add(id(values))

    return statement


def _pick_next_values_node(statement: exp.Expr, unresolved: set[int]) -> exp.Values | None:
    """
    Return the next exp.Values node in the statement not present in `unresolved`.

    This intentionally re-scans the tree every iteration because prior conversions
    can introduce new Values nodes.
    """
    for candidate in statement.find_all(exp.Values):
        if id(candidate) not in unresolved:
            return t.cast(exp.Values, candidate)
    return None


def _cte_ancestor_in_scope(statement: exp.Expr, values: exp.Values) -> exp.CTE | None:
    """Return the enclosing CTE only if it belongs to the current statement's subtree.

    Avoids erroneously picking a CTE that is outside the current `statement` root
    (a ghost ancestor through parent links), which would misclassify VALUES shape.
    """
    cte = values.find_ancestor(exp.CTE)
    if cte is None:
        return None

    ctes_in_scope = {id(c) for c in statement.find_all(exp.CTE)}
    if id(cte) not in ctes_in_scope:
        return None

    return t.cast(exp.CTE, cte)


def _handle_values_in_insert(
    values: exp.Values,
    parent: exp.Insert,
    is_top_level: bool,
    query,
) -> t.Optional[exp.Expr]:
    """
    Handle VALUES directly under an INSERT expression.

    Returns a possibly updated top-level statement when the INSERT itself is
    replaced and it is the top-level statement; otherwise returns None.
    """
    converted = _convert_values_to_select(query, values, parent)
    if isinstance(converted, exp.Insert) and is_top_level:
        return converted
    return None


def _handle_values_in_create(
    values: exp.Values,
    parent: exp.Create,
    query,
) -> None:
    """
    Handle VALUES directly under a CREATE ... AS expression.
    """
    _convert_values_to_select(query, values, parent)


def _rewrite_values_in_table_position(values: exp.Values, dialect: str) -> None:
    """
    Rewrite VALUES used in FROM/JOIN/LATERAL positions.

    Supports both:
    - Subquery(VALUES ...) shapes, updating the inner expression and preserving
      the outer alias/columns.
    - Direct 'FROM (VALUES ...)' shapes, converting and transferring aliases.
    """
    # SELECT (VALUES ...)
    outer_subquery = values.find_ancestor(exp.Subquery)
    if outer_subquery is not None and outer_subquery.this is values:
        converted = convert_values_to_select(
            expression=values,
            dialect=dialect,
        )
        if isinstance(converted, exp.Subquery):
            converted = converted.this  # unwrap nested Subquery
        outer_subquery.set("this", converted)
        return

    # SELECT FROM (VALUES ...)
    parent_select = values.parent_select
    from_ = parent_select and parent_select.args.get("from_")
    if from_ and from_.this is values:
        converted = convert_values_to_select(
            expression=values,
            dialect=dialect,
        )
        # Set the table alias
        original_alias = values.args.get("alias")
        if isinstance(converted, exp.Subquery):
            if original_alias and not converted.args.get("alias"):
                converted.set("alias", original_alias)
            from_.set("this", converted)


def _convert_values_to_select(query: Q, expression: exp.Values, statement: E) -> E:
    """
    Convert a `VALUES(...)` clause into a `SELECT ... UNION ALL SELECT ...` form
    and rewrite the parent statement in-place.
    """
    if not isinstance(expression, exp.Values):
        return statement

    # Resolve the column names
    if isinstance(statement, exp.CTE):
        columns = statement.alias_column_names
        if not columns:
            columns = [e.name for e in statement.root().this.expressions]
    elif not isinstance(statement, exp.Values):
        columns = [e.name for e in statement.this.expressions]
    else:
        columns = []

    # Fallback: look up from object mapping
    values_lists: t.List[exp.Tuple] = expression.expressions
    child_table = None

    if not columns:
        try:
            child_table = query.get_target_as_table()
            cols = query.object_mapping.find_columns_for_table(child_table)
            columns = list(cols)[: len(values_lists[0].expressions)]
        except exception.SqlLeafException:
            pass

    if not child_table:
        try:
            child_table = query.get_target_as_table()
        except exception.SqlLeafException:
            pass

    # Build the 'SELECT ... UNION ALL SELECT ...'
    new_statement = convert_values_to_select(
        expression=expression,
        dialect=query.dialect,
        column_names=columns,
    )

    # Rewrite the parent statement
    if isinstance(statement, exp.Insert):
        insert_expr = exp.insert(
            expression=new_statement,
            columns=statement.this.expressions,
            into=child_table or statement.this,
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


def convert_values_to_select(
    expression: exp.Values,
    dialect: str,
    column_names: t.Optional[t.List[str]] = None,
) -> exp.Expr:
    """
    Convert an exp.Values into an exp.Select or exp.Union.
    """
    values_lists: t.List[exp.Tuple] = expression.expressions
    if not column_names:
        column_names = list(default_column_index_iterator(dialect, values_lists[0].expressions))

    selects = []
    for val_list in values_lists:
        values = val_list.expressions
        cols = [exp.alias_(val, str(col)) for col, val in zip(column_names, values)]
        selects.append(cols)

    if len(selects) > 1:
        new_selects = [exp.select(*select) for select in selects]
        return_expr = exp.union(*new_selects, distinct=False)
    else:
        return_expr = exp.select(*selects[0])

    # Wrap the query in a subquery if it's not a top-level statement
    return return_expr.subquery() if expression.parent_select else return_expr
