from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes,
    ColumnNode,
)
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class PostgresBaseGenerator(BaseGenerator):
    dialect = "postgres"

    def process_table(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.Table = processor_ctx.expr
        if "rows_from" in expr.args:
            downstream_exprs = []
            for table_function in expr.args["rows_from"]:
                # Determine the immediate children of the expression.
                # These are either table functions or aliases to table functions (ColumnDefs)
                cols = list(table_function.find_all(exp.ColumnDef))
                downstream_exprs.extend(cols if cols else [table_function])

            child_column_name = processor_ctx.child_node_attrs.expr.name
            # Get the expression associated with the column name
            for i, col in enumerate(expr.alias_column_names):
                if col == child_column_name:
                    return None, [downstream_exprs[i]]

        elif expr.arg_key == "rows_from":
            # A table function inside a 'ROWS FROM'
            return None, [expr.this]

        return super().process_table(processor_ctx, ctx)

    def process_column_def(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.ColumnDef = processor_ctx.expr
        processor_ctx = replace(processor_ctx, new_data_type=expr.kind)

        if isinstance(expr.parent, exp.TableAlias):
            # An alias to a table function inside 'ROWS FROM'
            table_alias = expr.parent.alias_or_name
            if not table_alias:
                # The table alias isn't found, return an error. e.g. the "a" in "a(x, y)"
                (before, token, after) = expr.parent.sql().partition("(")
                table_alias = f"{token}{after}"
                raise exception.SqlLeafException(f"The table alias '{table_alias}' must have a name.")

            node_attrs = ColumnNode(
                catalog="",
                schema="",
                table=table_alias,
                column=expr.name,
                processor_ctx=processor_ctx,
                ctx=ctx,
            )
            table_function: exp.Table = expr.parent.parent
            return node_attrs, [table_function]

        return None, []
