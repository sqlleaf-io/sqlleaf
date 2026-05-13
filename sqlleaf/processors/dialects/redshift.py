from __future__ import annotations

import logging
import typing as t
from functools import singledispatchmethod

from hgext.children import children
from sqlglot import exp
from sqlglot.optimizer import Scope

from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes, ColumnNode,
)
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class RedshiftGenerator(BaseGenerator):
    dialect = "redshift"

    @singledispatchmethod
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_pivot(self, expr: exp.Pivot, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # TODO: process agg funcs
        pivot, pivot_column_mapping = _get_pivot(processor_ctx.scope)

        downstream_columns = []
        c = processor_ctx.scope.columns[ctx.select_index]

        column_name = c.name
        if any(column_name == pivot_column.name for pivot_column in pivot.args["columns"]):
            downstream_columns.extend(pivot_column_mapping[column_name])
        else:
            # The column is not in the pivot, so it must be an implicit column of the
            # pivoted source -- adapt column to be from the implicit pivoted source.
            downstream_columns.append(exp.column(c.this, table=pivot.parent.alias_or_name))

        parent = processor_ctx.child_node_attrs
        grandparents = downstream_columns
        yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)
        # return None, downstream_columns

    @process.register
    def process_column(self, expr: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        pivot = _get_pivot_expr(processor_ctx.scope)
        if pivot and pivot.alias_or_name == expr.table:
            parent = processor_ctx.child_node_attrs
            grandparents = [pivot]
            yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)
        else:
            yield from super().process(expr, processor_ctx, ctx)

    @process.register
    def process_location(self, expr: exp.LocationProperty, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        CREATE EXTERNAL TABLE ... LOCATION
        """
        location = expr.this
        child_node = processor_ctx.child_node_attrs
        query = processor_ctx.query
        table = query.child_table

        # Create: column[name kind=file subkind=text type=INT path=s3://my-bucket/a/b/c]
        column_node = ColumnNode(
            catalog=table.catalog,
            schema="",
            table="",
            column=child_node.column,
            processor_ctx=processor_ctx,
            ctx=ctx,
            skip_table_properties=True,
        )
        format = query.statement_transformed.args["properties"].find(exp.FileFormatProperty).this
        column_node.set_file_properties(format=format, path=location.name)

        yield column_node, processor_ctx.child_node_attrs


def _get_pivot_expr(scope: Scope) -> exp.Pivot | None:
    pivots = scope.pivots if scope else []
    pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
    return pivot


def _get_pivot(scope: Scope) -> t.Tuple[exp.Pivot, dict]:
    """
    Get information related to PIVOT statements.
    """
    pivot_column_mapping = {}
    pivot = _get_pivot_expr(scope)
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
