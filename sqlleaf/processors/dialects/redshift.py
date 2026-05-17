from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp
from sqlglot.optimizer import Scope

from sqlleaf import util, exception
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes, ColumnNode, PivotNode, UnpivotNode,
)
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class RedshiftGenerator(BaseGenerator):
    dialect = "redshift"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        yield from super().process(expr, processor_ctx, ctx)

    @process.register
    def process_unpivot(self, expr: exp.Pivot, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT * FROM ... UNPIVOT ( ... )
        """
        # Given expression:
        #   UNPIVOT ( <expression> FOR <field> IN (<column> AS <value>) )
        # We have lineage:
        #   <column> -> UNPIVOT -> <expression>
        #   <value> -> UNPIVOT -> <field>
        selected_column = processor_ctx.scope.columns[ctx.select_index]
        pivot_expression = expr.expressions[0]
        pivot_field = expr.fields[0]

        if selected_column.name == pivot_expression.name:
            arg = "this"
        elif selected_column.name == pivot_field.this.name:
            arg = "alias"
        else:
            message = f"Could not find column '{selected_column.name}' in UNPIVOT expression"
            raise exception.SqlLeafException(message=message)

        # Create an unpivot node for each downstream column/expression
        for pivot_alias in pivot_field.expressions:
            pivot_value = pivot_alias.args[arg]

            unpivot_node = UnpivotNode(
                processor_ctx=processor_ctx,
                ctx=ctx,
            )
            source = pivot_value.name if arg == "this" else ""  # Only columns are sources for now
            unpivot_node.set(source=source, target=selected_column.name)
            yield unpivot_node, processor_ctx.child_node_attrs

            yield from self.do_grandparents([pivot_value], unpivot_node, processor_ctx, ctx)


    @process.register
    def process_pivot(self, expr: exp.Pivot, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # Find the associated expression for the column, and process it
        selected_column = processor_ctx.scope.columns[ctx.select_index]
        pivot_column_mapping = _get_pivot_mapping(expr)

        # The associated column and expression
        column_and_expr = pivot_column_mapping[selected_column.name]
        pivot_expr = column_and_expr["expression"]

        pivot_node = PivotNode(
            processor_ctx=processor_ctx,
            ctx=ctx,
        )
        pivot_node.set(source=pivot_expr.alias_or_name, target=selected_column.alias_or_name)
        yield pivot_node, processor_ctx.child_node_attrs

        grandparents = [pivot_expr]
        yield from self.do_grandparents(grandparents, pivot_node, processor_ctx, ctx)


    @process.register
    def process_column(self, expr: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        pivot = _get_pivot_expr(processor_ctx.scope)
        if (pivot and pivot.alias_or_name == expr.table and
            not isinstance(processor_ctx.child_node_attrs, UnpivotNode)  # Prevent infinite recursion
        ):
            processor_ctx = replace(processor_ctx, expr=pivot)
            if pivot.unpivot:
                yield from self.process_unpivot(pivot, processor_ctx, ctx)
            else:
                yield from self.process_pivot(pivot, processor_ctx, ctx)
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
    pivot = pivots[0] if len(pivots) == 1 else None
    return pivot


def _get_pivot_mapping(expr: exp.Pivot) -> dict:
    """
    Get information related to PIVOT statements.
    """
    pivot_column_mapping = {}
    # For each aggregation function, the pivot creates a new column for each field in category
    # combined with the aggfunc. So the columns parsed have this order: cat_a_value_sum, cat_a,
    # b_value_sum, b. Because of this step wise manner the aggfunc 'sum(value) as value_sum'
    # belongs to the column indices 0, 2, and the aggfunc 'max(price)' without an alias belongs
    # to the column indices 1, 3. Here, only the columns used in the aggregations are of interest
    # in the lineage, so lookup the pivot column name by index and map that with the columns used
    # in the aggregation.
    #
    # Example: PIVOT (SUM(value) AS value_sum, MAX(price)) FOR category IN ('a' AS cat_a, 'b')
    pivot_columns = expr.args["columns"]
    pivot_aggs_count = len(expr.expressions)

    for i, agg in enumerate(expr.expressions):
        agg_cols = list(agg.find_all(exp.Column))
        for col_index in range(i, len(pivot_columns), pivot_aggs_count):
            pivot_column_mapping[pivot_columns[col_index].name] = {
                'column': agg_cols,
                'expression': agg
            }

    return pivot_column_mapping
