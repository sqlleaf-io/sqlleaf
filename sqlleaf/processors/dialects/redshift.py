from __future__ import annotations

import logging
import typing as t
from functools import singledispatchmethod

from sqlglot import exp
from sqlglot.optimizer import Scope

from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes,
)
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class RedshiftBaseGenerator(BaseGenerator):
    dialect = "redshift"

    @singledispatchmethod
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_pivot(self, cls: exp.Pivot, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # TODO: process agg funcs
        expr: exp.Pivot = processor_ctx.expr

        pivot, pivot_column_mapping = get_pivot(processor_ctx.scope)

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

def get_pivot(scope: Scope) -> t.Tuple[exp.Pivot, dict]:
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
