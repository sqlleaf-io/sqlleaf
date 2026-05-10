from __future__ import annotations

import logging
import typing as t
from functools import singledispatchmethod

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
    def process(self, cls: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        return super().process(cls, processor_ctx, ctx)

    @process.register
    def process_pivot(self, cls: exp.Pivot, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # TODO: process agg funcs
        expr: exp.Pivot = processor_ctx.expr

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

        return None, downstream_columns

    @process.register
    def process_column(self, cls: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.Column = processor_ctx.expr

        scope = processor_ctx.scope
        if scope:
            pivots = scope.pivots
            pivot: exp.Pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
            if pivot and pivot.alias_or_name == expr.table:
                return None, [pivot]

        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_location(self, cls: exp.LocationProperty, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        CREATE EXTERNAL TABLE ... LOCATION
        """
        expr: exp.LocationProperty = processor_ctx.expr
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

        return column_node, []


def _get_pivot(scope: Scope) -> t.Tuple[exp.Pivot, dict]:
    """
    Get information related to PIVOT statements.
    """
    pivot_column_mapping = {}
    pivots = scope.pivots
    pivot: exp.Pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
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
