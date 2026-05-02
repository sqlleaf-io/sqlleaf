from __future__ import annotations
import logging
from dataclasses import dataclass

from sqlglot import exp
from sqlglot.optimizer import (
    Scope,
    find_all_in_scope,
)

from sqlleaf import exception

logger = logging.getLogger("sqlleaf")

TableOrScopeType = exp.Table | Scope


@dataclass(frozen=True)
class Node:
    expression: exp.Expression
    current_depth: int
    scope: TableOrScopeType = None


def walk_query_scope(column: exp.Column, scope: Scope, current_depth: int = 0):
    if isinstance(scope.expression, exp.Subquery):
        for source in scope.subquery_scopes:
            logger.debug("Yielding from first subquery scope")
            yield from walk_query_scope(
                column=column,
                scope=source,
                current_depth=current_depth + 1,
            )
    elif isinstance(scope.expression, exp.SetOperation):
        # UNION, EXCEPT, etc
        index = get_column_index(column, scope)

        for s in scope.union_scopes:
            logger.debug("Yielding from union scope")
            yield from walk_query_scope(
                column=index,
                scope=s,
                current_depth=current_depth + 1,
            )
    else:
        # Create the node for this step in the lineage chain, and attach it to the previous one.
        select = get_select(column, scope)
        node = Node(
            expression=select,
            scope=scope,
            current_depth=current_depth,
        )
        yield node
        logger.debug("[1] Created Node '%s', Expr: %s, Id: %s", column, select.sql(), id(node))

        subquery_scopes = {id(subquery_scope.expression): subquery_scope for subquery_scope in scope.subquery_scopes}

        for subquery in find_all_in_scope(select, exp.UNWRAPPED_QUERIES):
            # e.g. SELECT ARRAY(SELECT 1), UPDATE x SET y = (SELECT 1)
            subquery_scope = subquery_scopes.get(id(subquery))
            if not subquery_scope:
                logger.warning("Unknown subquery scope: %s", subquery.sql())
                continue

            for name in subquery.named_selects:
                logger.debug("Yielding from second subquery scope")
                yield from walk_query_scope(
                    column=exp.column(name),
                    scope=subquery_scope,
                    current_depth=current_depth + 1,
                )


def get_select(column: exp.Column | int, scope: Scope):
    if isinstance(column, int):
        # The index of the query in "SELECT 1 UNION SELECT 2"
        select = scope.expression.selects[column]
    else:
        if isinstance(scope.expression, exp.Values):
            # SELECT FROM (VALUES ())
            selects = [scope.expression]
        else:
            selects = [select for select in scope.expression.selects if select.alias_or_name == column.name]
        if len(selects) > 1:
            message = f"Column reference '{column}' is ambiguous ({len(selects)} possible options)"
            raise exception.SqlLeafException(message)
        if selects:
            select = selects[0]
        else:
            select = scope.expression
    return select


def get_column_index(column: exp.Column | int, scope: Scope):
    index = (
        column
        if isinstance(column, int)
        else next(
            (i for i, sel in enumerate(scope.expression.selects) if sel.alias_or_name == column.name),
            -1,  # mypy will not allow a None here, but a negative index should never be returned
        )
    )
    if index == -1:
        raise ValueError(f"Could not find {column.name} in {scope.expression}")
    return index
