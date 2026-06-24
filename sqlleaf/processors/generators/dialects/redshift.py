from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp
from sqlglot.optimizer import Scope

from sqlleaf import exception
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    FileColumnNode,
    PivotNode,
    UnpivotNode,
)
from sqlleaf.processors.generators.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger

logger = logging.getLogger("sqlleaf")


class RedshiftGenerator(BaseGenerator):
    dialect = "redshift"

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_unpivot(
        self, expr: exp.Pivot, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT * FROM ... UNPIVOT ( ... )
        """
        # Given expression:
        #   UNPIVOT ( <expression> FOR <field> IN (<column> AS <value>) )
        # We have lineage:
        #   <column> -> UNPIVOT -> <expression>
        #   <value> -> UNPIVOT -> <field>
        scope = t.cast(Scope, gen_ctx.scope)
        selected_column = scope.columns[pos_ctx.select_index]
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
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            source = pivot_value.name if arg == "this" else ""  # Only columns are sources for now
            unpivot_node.set(source=source, target=selected_column.name)
            yield EdgeToCreate(unpivot_node, gen_ctx.child_node)

            yield from self.do_grandparents([pivot_value], unpivot_node, gen_ctx, pos_ctx)

    @process.register
    def process_pivot(
        self, expr: exp.Pivot, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # Find the associated expression for the column, and process it
        scope = t.cast(Scope, gen_ctx.scope)
        selected_column = scope.columns[pos_ctx.select_index]
        pivot_column_mapping = _get_pivot_mapping(expr)

        # The associated column and expression
        column_and_expr = pivot_column_mapping[selected_column.name]
        pivot_expr = column_and_expr["expression"]

        pivot_node = PivotNode(
            gen_ctx=gen_ctx,
            pos_ctx=pos_ctx,
        )
        pivot_node.set(source=pivot_expr.alias_or_name, target=selected_column.alias_or_name)
        yield EdgeToCreate(pivot_node, gen_ctx.child_node)

        grandparents = [pivot_expr]
        yield from self.do_grandparents(grandparents, pivot_node, gen_ctx, pos_ctx)

    @process.register
    def process_column(
        self, expr: exp.Column, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        scope = t.cast(Scope, gen_ctx.scope)
        pivot = _get_pivot_expr(scope)
        if (
            pivot
            and pivot.alias_or_name == expr.table
            and not isinstance(gen_ctx.child_node, UnpivotNode)  # Prevent infinite recursion
        ):
            gen_ctx = replace(gen_ctx, expr=pivot)
            if pivot.unpivot:
                yield from self.process_unpivot(pivot, gen_ctx, pos_ctx)
            else:
                yield from self.process_pivot(pivot, gen_ctx, pos_ctx)
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_location(
        self, expr: exp.LocationProperty, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        CREATE EXTERNAL TABLE ... LOCATION
        """
        location = expr.this
        child_node = gen_ctx.child_node

        # TODO: change to source/target info

        # Create: column[name kind=file format=text type=INT path=s3://my-bucket/a/b/c]
        file_format = gen_ctx.query.statement.args["properties"].find(exp.FileFormatProperty).this
        column_node = FileColumnNode(
            column=child_node.name,
            #file_format=file_format,
            file_path=location.name,
            gen_ctx=gen_ctx,
            pos_ctx=pos_ctx,
        )

        yield EdgeToCreate(column_node, child_node)


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
            pivot_column_mapping[pivot_columns[col_index].name] = {"column": agg_cols, "expression": agg}

    return pivot_column_mapping
