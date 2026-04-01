from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, field, replace

from sqlglot import Schema, exp, maybe_parse
from sqlglot.errors import SqlglotError
from sqlglot.optimizer import (
    Scope,
    build_scope,
    find_all_in_scope,
    normalize_identifiers,
    qualify,
)
from sqlglot.optimizer.scope import ScopeType

if t.TYPE_CHECKING:
    from sqlglot.dialects.dialect import DialectType

from sqlleaf import util

logger = logging.getLogger("sqlleaf")

"""
This file was taken from sqlglot and slightly modified.
"""
@dataclass(frozen=True)
class Node:
    name: str
    column: exp.Expression  # Usually exp.Column
    expression: exp.Expression
    source: exp.Expression
    downstream: t.List[Node] = field(default_factory=list)
    upstream: t.List[Node] = field(default_factory=list)
    is_cte: bool = False
    source_name: str = ""
    reference_node_name: str = ""

    def walk(self) -> t.Iterator[Node]:
        yield self

        for d in self.downstream:
            yield from d.walk()


def lineage(
    column: str | exp.Column,
    sql: str | exp.Expression,
    schema: t.Optional[t.Dict | Schema] = None,
    sources: t.Optional[t.Mapping[str, str | exp.Query]] = None,
    dialect: DialectType = None,
    scope: t.Optional[Scope] = None,
    trim_selects: bool = True,
    **kwargs,
) -> Node:
    """Build the lineage graph for a column of a SQL query.

    This is taken from the `sqlglot.lineage` module and extended with custom features.

    Args:
        column: The column to build the lineage for.
        sql: The SQL string or expression.
        schema: The schema of tables.
        sources: A mapping of queries which will be used to continue building sqlleaf.
        dialect: The dialect of input SQL.
        scope: A pre-created scope to use instead.
        trim_selects: Whether or not to clean up selects by trimming to only relevant columns.
        **kwargs: Qualification optimizer kwargs.

    Returns:
        A lineage node.
    """
    expression = maybe_parse(sql, dialect=dialect)
    column = normalize_identifiers.normalize_identifiers(column, dialect=dialect)

    if sources:
        expression = exp.expand(
            expression,
            {k: t.cast(exp.Query, maybe_parse(v, dialect=dialect)) for k, v in sources.items()},
            dialect=dialect,
        )

    if not scope:
        expression = qualify.qualify(
            expression,
            dialect=dialect,
            schema=schema,
            **{"validate_qualify_columns": False, "identify": False, **kwargs},  # type: ignore
        )

        scope = build_scope(expression)

    if not scope:
        raise SqlglotError("Cannot build lineage, sql must be SELECT")

    if not any(select.alias_or_name == column.name for select in scope.expression.selects):
        raise SqlglotError(f"Cannot find column '{column.name}' in query.")

    return to_node(column, scope, dialect, trim_selects=trim_selects)


def to_node(
    column: exp.Column,
    scope: Scope,
    dialect: DialectType,
    scope_name: t.Optional[str] = None,
    upstream: t.Optional[Node] = None,
    source_name: t.Optional[str] = None,
    reference_node_name: t.Optional[str] = None,
    trim_selects: bool = True,
) -> Node:
    """
    This function was taken from sqlglot and modified somewhat to produce better lineage.
    Source: https://sqlglot.com/sqlglot/lineage.html#to_node
    """
    # Find the specific select clause that is the source of the column we want.
    # This can either be a specific, named select or a generic `*` clause.
    select = (
        scope.expression.selects[column]
        if isinstance(column, int)
        else next(
            (select for select in scope.expression.selects if select.alias_or_name == column.name),
            exp.Star() if scope.expression.is_star else scope.expression,
        )
    )

    if isinstance(scope.expression, exp.Subquery):
        for source in scope.subquery_scopes:
            return to_node(
                column=column,
                scope=source,
                dialect=dialect,
                upstream=upstream,
                source_name=source_name,
                reference_node_name=reference_node_name,
                trim_selects=trim_selects,
            )
    if isinstance(scope.expression, exp.SetOperation):
        name = type(scope.expression).__name__.upper()
        if not upstream:
            upstream = Node(
                name=name,
                column=column,
                source=scope.expression,
                expression=select,
            )
            logger.debug("[6] Created Node '%s'", column)

        index = (
            column
            if isinstance(column, int)
            else next(
                (i for i, select in enumerate(scope.expression.selects) if select.alias_or_name == column.name or select.is_star),
                -1,  # mypy will not allow a None here, but a negative index should never be returned
            )
        )

        if index == -1:
            raise ValueError(f"Could not find {column.name} in {scope.expression}")

        for s in scope.union_scopes:
            to_node(
                column=index,
                scope=s,
                dialect=dialect,
                upstream=upstream,
                source_name=source_name,
                reference_node_name=reference_node_name,
                trim_selects=trim_selects,
            )

        return upstream

    if trim_selects and isinstance(scope.expression, exp.Select):
        # For better ergonomics in our node labels, replace the full select with
        # a version that has only the column we care about.
        #   "x", SELECT x, y FROM foo
        #     => "x", SELECT x FROM foo
        source = t.cast(exp.Expression, scope.expression.select(select, append=False))
    else:
        source = scope.expression

    # Create the node for this step in the lineage chain, and attach it to the previous one.
    node = Node(
        name=f"{scope_name}.{column.name}" if scope_name else str(column),
        column=column,
        source=source,
        expression=select,
        source_name=source_name or "",
        reference_node_name=reference_node_name or "",
    )
    logger.debug("[1] Created Node '%s', Expr: %s", column, util.unwrap_expression(select))

    if upstream:
        upstream.downstream.append(node)
        node.upstream.append(upstream)

    subquery_scopes = {id(subquery_scope.expression): subquery_scope for subquery_scope in scope.subquery_scopes}

    for subquery in find_all_in_scope(select, exp.UNWRAPPED_QUERIES):
        subquery_scope = subquery_scopes.get(id(subquery))
        if not subquery_scope:
            logger.warning("Unknown subquery scope: %s", subquery.sql(dialect=dialect))
            continue

        for name in subquery.named_selects:
            to_node(
                column=exp.column(name),
                scope=subquery_scope,
                dialect=dialect,
                upstream=node,
                trim_selects=trim_selects,
            )

    # if the select is a star add all scope sources as downstreams
    if select.is_star:
        for source in scope.sources.values():
            if isinstance(source, Scope):
                source = source.expression
            n = Node(
                name=_to_node_name(select),
                column=column,
                source=source,
                upstream=[node],
                expression=source,
            )
            node.downstream.append(n)
            logger.debug("[2] Created Node from star: %s", node.name)

    # Find all columns that went into creating this one to list their lineage nodes.
    source_columns = util.unique(find_all_in_scope(select, exp.Column))

    # If the source is a UDTF find columns used in the UTDF to generate the table
    if isinstance(source, exp.UDTF):
        source_columns |= set(source.find_all(exp.Column))
        derived_tables = [source.expression.parent for source in scope.sources.values() if isinstance(source, Scope) and source.is_derived_table]
    else:
        derived_tables = scope.derived_tables

    source_names = {dt.alias: dt.comments[0].split()[1] for dt in derived_tables if dt.comments and dt.comments[0].startswith("source: ")}

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

        pivot_column_mapping = {}
        for i, agg in enumerate(pivot.expressions):
            agg_cols = list(agg.find_all(exp.Column))
            for col_index in range(i, len(pivot_columns), pivot_aggs_count):
                pivot_column_mapping[pivot_columns[col_index].name] = agg_cols

    for c in source_columns:
        table = c.table
        source = scope.sources.get(table)

        if isinstance(source, Scope):
            reference_node_name = None
            if source.scope_type == ScopeType.DERIVED_TABLE and table not in source_names:
                reference_node_name = table
            elif source.scope_type == ScopeType.CTE:
                selected_node, _ = scope.selected_sources.get(table, (None, None))
                reference_node_name = selected_node.name if selected_node else None
                # Use the CTE's name instead of its alias
                c.args["table"] = exp.to_identifier(reference_node_name)
                node = replace(node, is_cte=True)

            # The table itself came from a more specific scope. Recurse into that one using the unaliased column name.
            to_node(
                column=c,
                scope=source,
                dialect=dialect,
                scope_name=reference_node_name,
                upstream=node,
                source_name=source_names.get(table) or source_name,
                reference_node_name=reference_node_name,
                trim_selects=trim_selects,
            )
        elif pivot and pivot.alias_or_name == c.table:
            downstream_columns = []

            column_name = c.name
            if any(column_name == pivot_column.name for pivot_column in pivot_columns):
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
                        scope_name=table,
                        dialect=dialect,
                        upstream=node,
                        source_name=source_names.get(table) or source_name,
                        reference_node_name=reference_node_name,
                        trim_selects=trim_selects,
                    )
                else:
                    source = source or exp.Placeholder()
                    n = Node(
                        name=_to_node_name(downstream_column),
                        # name=downstream_column.sql(comments=False),
                        column=downstream_column,
                        source=source,
                        upstream=[node],
                        expression=source,
                    )
                    node.downstream.append(n)
                    logger.debug("[4] Created Node '%s' downstream of '%s'", n.name, node.name)

        else:
            # The source is not a scope and the column is not in any pivot - we've reached the end
            # of the line. At this point, if a source is not found it means this column's lineage
            # is unknown. This can happen if the definition of a source used in a query is not
            # passed into the `sources` map.
            source = source or exp.Placeholder()

            # Change the column's source table to be its name, not its alias
            if isinstance(source, exp.Table):
                if source.catalog:
                    c.set("catalog", exp.to_identifier(source.catalog))
                if source.db:
                    c.set("db", exp.to_identifier(source.db))
                if source.name:
                    if dialect == 'snowflake':
                        if source.this.this.args.get('quoted', False):
                            c.set("table", exp.to_identifier(source.name))
                    else:
                        c.set("table", exp.to_identifier(source.name))

            n = Node(
                name=c.sql(comments=False),
                column=c,
                source=source,
                upstream=[node],
                expression=source,
            )
            node.downstream.append(n)
            logger.debug(
                "[5] Created Node '%s' downstream of '%s'",
                n.column.name,
                node.column.name,
            )

    return node


def _to_node_name(expr):
    return expr.key
