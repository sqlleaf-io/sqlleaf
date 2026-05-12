from __future__ import annotations

import logging
import typing as t
from dataclasses import replace
from functools import singledispatchmethod

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes,
    ColumnNode, SequenceNode,
)
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class PostgresGenerator(BaseGenerator):
    dialect = "postgres"

    @singledispatchmethod
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_table(self, expr: exp.Table, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        Process a table or a table function.
        This is a bit awkward as we have the sequence: Table -> ColumnDef -> Table
        for table functions.
        """
        if "rows_from" in expr.args:
            downstream_exprs = []
            for table_function in expr.args["rows_from"]:
                # Determine the immediate children of the expression.
                # These are either table functions or aliases to table functions (ColumnDefs)
                cols = list(table_function.find_all(exp.ColumnDef))
                downstream_exprs.extend(cols if cols else [table_function])

            # Get the expression associated with the column name
            child_column_name = processor_ctx.child_node_attrs.expr.name
            for i, col in enumerate(expr.alias_column_names):
                if col == child_column_name:
                    # Returns ColumnDef | Function
                    return None, [downstream_exprs[i]]

        elif expr.arg_key == "rows_from":
            # A table function inside a 'ROWS FROM'
            # TODO: reset the index. This should be part of a scope traversal first.
            return None, [expr.this]

        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_anonymous(self, expr: exp.Anonymous, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        if isinstance(expr.parent, (exp.Dot,)):
            # Postgres UDFs don't support catalogs
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
            full_name = f"{schema}.{function}"
        else:
            # e.g. The PG sequence function nextval('serial') is anonymous
            schema = ""
            function = expr.name
            full_name = function

        # Process a sequence
        if not schema and function in [
            "nextval",
            "currval",
            "setval",
        ]:
            # 'lastval()' is not supported since it requires tracking state
            seq_name_expr: exp.Literal = expr.args["expressions"][0]

            # Ensure the sequence exists
            seq_table = exp.table_(table=seq_name_expr.name, db=schema)
            if not processor_ctx.object_mapping.find_query(kind="sequence", table=seq_table):
                logger.warning(f"Sequence '{full_name}' not found.")

            node_attrs = SequenceNode(name=seq_name_expr.name, processor_ctx=processor_ctx, ctx=ctx)
            return node_attrs, []

        return super().process(expr, processor_ctx, ctx)

    @process.register
    def process_column_def(self, expr: exp.ColumnDef, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
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
