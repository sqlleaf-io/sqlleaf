from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, field

from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer import (
    Scope,
    find_all_in_scope,
    normalize_identifiers,
)
from sqlglot.optimizer.scope import ScopeType

from sqlleaf import exception
from sqlleaf.objects.query_types import Query, ProcedureQuery

logger = logging.getLogger("sqlleaf")

"""
This file was taken from sqlglot and slightly modified.
"""


@dataclass(frozen=False)
class Node:
    name: str
    column: exp.Expression  # Usually exp.Column
    expression: exp.Expression
    source: exp.Expression
    downstream: t.List[Node] = field(default_factory=list)
    upstream: t.List[Node] = field(default_factory=list)
    pivot: exp.Pivot = None
    is_parent_a_cte: bool = False
    is_parent_a_recursive_cte: bool = False
    is_parent_a_derived_table: bool = False
    recursive_cte_member_kind: str = ""  # anchor | recursive
    source_name: str = ""

    def walk(self) -> t.Iterator[Node]:
        yield self

        for d in self.downstream:
            yield from d.walk()


def lineage(
    column: str | exp.Column,
    query: Query,
    scope: t.Optional[Scope] = None,
) -> Node:
    """Build the lineage graph for a column of a SQL query.

    This is taken from the `sqlglot.lineage` module and extended with custom features.

    Args:
        column: The column to build the lineage for.
        query: the Query containing this expression
        scope: A pre-created scope to use instead.

    Returns:
        A lineage node.
    """
    column = normalize_identifiers.normalize_identifiers(column, dialect=query.dialect)

    if not any(select.alias_or_name == column.name for select in scope.expression.selects):
        raise SqlglotError(f"Cannot find column '{column.name}' in query.")

    return to_node(column, scope, query)


def to_node(
    column: exp.Column,
    scope: Scope,
    query: Query,
    scope_name: t.Optional[str] = None,
    upstream: t.Optional[Node] = None,
    source_name: t.Optional[str] = None,
) -> Node:
    """
    This function was taken from sqlglot and modified somewhat to produce better lineage.
    Source: https://sqlglot.com/sqlglot/lineage.html#to_node
    """
    # Find the specific select clause that is the source of the column we want.
    # This can either be a specific, named select or a generic `*` clause.

    select = get_select(column, scope)
    pivot, pivot_column_mapping = get_pivot(scope)

    if isinstance(scope.expression, exp.Subquery):
        for source in scope.subquery_scopes:
            return to_node(
                column=column,
                scope=source,
                query=query,
                upstream=upstream,
                source_name=source_name,
            )
    if isinstance(scope.expression, exp.SetOperation):
        # UNION, EXCEPT, etc
        name = type(scope.expression).__name__.upper()
        # TODO: skip this if possible?; it's dropped by outside func
        if not upstream:
            upstream = Node(
                name=name,
                column=column,
                source=scope.expression,
                expression=select,
                pivot=pivot,
            )
            logger.debug("[6] Created Node '%s'", column)

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

        for s in scope.union_scopes:
            to_node(
                column=index,
                scope=s,
                query=query,
                upstream=upstream,
                source_name=source_name,
            )
        return upstream

    # Create the node for this step in the lineage chain, and attach it to the previous one.
    node = Node(
        name=f"{scope_name}.{column.name}" if scope_name else str(column),
        column=column,
        source=select,
        expression=select,
        source_name=source_name or "",
        pivot=pivot,
    )
    logger.debug("[1] Created Node '%s', Expr: %s, Id: %s", column, select.sql(), id(node))
    if upstream:
        upstream.downstream.append(node)
        node.upstream.append(upstream)

    subquery_scopes = {id(subquery_scope.expression): subquery_scope for subquery_scope in scope.subquery_scopes}

    for subquery in find_all_in_scope(select, exp.UNWRAPPED_QUERIES):
        subquery_scope = subquery_scopes.get(id(subquery))
        if not subquery_scope:
            logger.warning("Unknown subquery scope: %s", subquery.sql(dialect=query.dialect))
            continue

        for name in subquery.named_selects:
            to_node(
                column=exp.column(name),
                scope=subquery_scope,
                query=query,
                upstream=node,
            )

    # Find all columns that went into creating this one to list their lineage nodes.
    source_columns = list(find_all_in_scope(select, exp.Column))
    seen_source_columns = []

    source = scope.expression
    # If the source is a UDTF find columns used in the UTDF to generate the table
    if isinstance(source, exp.UDTF):
        source_columns.extend(list(set(source.find_all(exp.Column))))

    for c in source_columns:
        table = c.table
        source = scope.sources.get(table)

        rename_table(c, source, query.dialect)

        if c in seen_source_columns:
            continue

        if isinstance(source, exp.Table) and "rows_from" in source.args:
            node.is_parent_a_derived_table = True

        if isinstance(source, Scope):
            selected_node = None

            if isinstance(source.expression, exp.Values):
                # SELECT FROM (VALUES())
                node.is_parent_a_derived_table = True
            elif source.scope_type == ScopeType.CTE:
                selected_node, _ = scope.selected_sources.get(table, (None, None))
                if not selected_node:
                    message = f"Table '{table}' is referenced but there is no FROM containing it."
                    raise exception.SqlLeafException(message=message)

                # Use the CTE's name instead of its alias
                c.args["table"] = exp.to_identifier(selected_node.name)
                node.is_parent_a_cte = True
                logger.debug("Set node to be a CTE.")

                # Check if the parent is a recursive CTE
                for cte in source.parent.ctes:
                    if cte.alias_or_name == selected_node.name:
                        with_: exp.With = cte.parent
                        if with_.recursive:
                            node.is_parent_a_recursive_cte = with_.recursive
                            logger.debug("Set node to be a recursive CTE.")
                        break

            if is_node_inside_a_recursive_cte(node):
                # Any further nodes are duplicates
                break

            # The table itself came from a more specific scope. Recurse into that one using the unaliased column name.
            to_node(
                column=c,
                scope=source,
                query=query,
                scope_name=selected_node,
                upstream=node,
                source_name=source_name,
            )
        elif pivot and pivot.alias_or_name == c.table:
            downstream_columns = []

            column_name = c.name
            if any(column_name == pivot_column.name for pivot_column in pivot.args["columns"]):
                downstream_columns.extend(pivot_column_mapping[column_name])
            else:
                # The column is not in the pivot, so it must be an implicit column of the
                # pivoted source -- adapt column to be from the implicit pivoted source.
                downstream_columns.append(exp.column(c.this, table=pivot.parent.alias_or_name))

            for downstream_column in downstream_columns:
                table = downstream_column.table
                source = scope.sources.get(table)

                if isinstance(source, Scope):
                    to_node(
                        column=downstream_column,
                        scope=source,
                        query=query,
                        scope_name=table,
                        upstream=node,
                        # source_name=source_names.get(table) or source_name,
                        source_name=source_name,
                    )
                else:
                    source = source or exp.Placeholder()
                    n = Node(
                        name=_to_node_name(downstream_column),
                        column=downstream_column,
                        source=source,
                        upstream=[node],
                        expression=source,
                        pivot=pivot,
                    )
                    node.downstream.append(n)
                    logger.debug("[4] Created Node '%s' downstream of '%s'", n.name, node.name)

        else:
            # The source is not a scope and the column is not in any pivot - we've reached the end
            # of the line. At this point, if a source is not found it means this column's lineage
            # is unknown. This can happen if the definition of a source used in a query is not
            # passed into the `sources` map.

            if not source:
                # Check if the column is a variable from a procedure definition
                if isinstance(root_query := query.get_root_query(), ProcedureQuery):
                    for col_def in root_query.get_column_defs():
                        if c.name == col_def.name and not c.table:
                            source = exp.Placeholder(this=col_def)
                            break

            if not source:
                message = f"Unknown column '{c.sql()}' in query: {c.parent_select.sql()}"
                raise exception.SqlLeafException(message)

            n = Node(
                name=c.sql(),
                column=c,
                source=source,
                upstream=[node],
                expression=source,
                pivot=pivot,
            )
            if isinstance(source, exp.Table) and "rows_from" in source.args:
                n.is_parent_a_derived_table = True

            node.downstream.append(n)
            logger.debug("[5] Created Node '%s', Expr: %s, Id: %s", c, source.sql(), id(n))

        seen_source_columns.append(c)

    return node


def get_select(column, scope):
    if isinstance(column, int):
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


def get_pivot(scope: Scope) -> t.Tuple[exp.Pivot, dict]:
    """
    Get information related to PIVOT statements.
    """
    pivot_column_mapping = {}
    pivots = scope.pivots
    pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
    if pivot:
        # For each aggregation function, the pivot creates a new column for each field in category
        # combined with the aggfunc. So the columns parsed have this order: cat_a_value_sum, cat_a,
        # b_value_sum, b. Because of this step wise manner the aggfunc 'sum(value) as value_sum'
        # belongs to the column indices 0, 2, and the aggfunc 'max(price)' without an alias belongs
        # to the column indices 1, 3. Here, only the columns used in the aggregations are of interest
        # in the lineage, so lookup the pivot column name by index and map that with the columns used
        # in the aggregation.
        #
        # Example: PIVOT (SUM(value) AS value_sum, MAX(price)) FOR category IN ('a' AS cat_a, 'b')
        pivot_columns = pivot.args["columns"]
        pivot_aggs_count = len(pivot.expressions)

        for i, agg in enumerate(pivot.expressions):
            agg_cols = list(agg.find_all(exp.Column))
            for col_index in range(i, len(pivot_columns), pivot_aggs_count):
                pivot_column_mapping[pivot_columns[col_index].name] = agg_cols

    return pivot, pivot_column_mapping


def rename_table(c: exp.Column, source, dialect: str):
    """
    Change the column's source table to be its fully qualified name, not its alias,
    so that the ColumnNode is provided complete information.
    """
    if isinstance(source, exp.Table):
        _c = c.copy()
        if source.catalog:
            c.set("catalog", exp.to_identifier(source.catalog))
        if source.db:
            c.set("db", exp.to_identifier(source.db))
        if source.name:
            if dialect == "snowflake":
                if source.this.args.get("quoted", False):  # exp.Identifier
                    c.set("table", exp.to_identifier(source.name))
            else:
                c.set("table", exp.to_identifier(source.name))
        if _c != c:
            logger.debug(f"Renamed node {_c.sql()} to {c.sql()}")


def _to_node_name(expr):
    return expr.key


def is_node_inside_a_recursive_cte(node: Node) -> bool:
    """
    Check if we're inside a recursive CTE
    """
    if parent_cte := node.expression.find_ancestor(exp.CTE):
        if parent_cte.parent.recursive:
            return True
    return False
