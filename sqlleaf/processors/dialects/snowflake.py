from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import util
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes,
    StageNode,
    FileNode,
)
from sqlleaf.objects.query_types import CopyQuery
from sqlleaf.processors.dialects import BaseGenerator

logger = logging.getLogger("sqlleaf")

class SnowflakeGenerator(BaseGenerator):
    dialect = "snowflake"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        yield from super().process(expr, processor_ctx, ctx)

    @process.register
    def process_put(self, expr: exp.Put, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
        - Creates two nodes: FileNode and StageNode
        """
        # This steps outside the 'process_node_objects()' main method, as
        # adding logic inside the default functions is too messy.
        # We may need to return to this later.
        file_ctx = replace(processor_ctx, expr=expr.args["this"])
        stage_ctx = replace(processor_ctx, expr=expr.args["target"])

        file_node = FileNode(processor_ctx=file_ctx, ctx=ctx)
        stage_node = StageNode(processor_ctx=stage_ctx, ctx=ctx)

        yield file_node, stage_node

    @process.register
    def process_column(self, expr: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        If the source is actually a Stage, don't try to create a Column.
        """
        query = processor_ctx.query
        if isinstance(query, CopyQuery) and query.is_source_a_stage:
            stage_name: exp.Var = query.source.this
            stage_ctx = replace(processor_ctx, expr=stage_name)
            parent = StageNode(processor_ctx=stage_ctx, ctx=ctx)
            yield parent, processor_ctx.child_node_attrs
        else:
            yield from super().process_column(expr, processor_ctx, ctx)
