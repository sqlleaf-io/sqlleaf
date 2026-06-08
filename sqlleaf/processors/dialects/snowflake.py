from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.node_types import (
    FileNode,
    StageColumnNode,
    StageNode,
)
from sqlleaf.objects.query_types import CopyQuery
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate

logger = logging.getLogger("sqlleaf")


class SnowflakeGenerator(BaseGenerator):
    dialect = "snowflake"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_put(
        self, expr: exp.Put, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
        - Creates two nodes: FileNode and StageNode
        """
        # This steps outside the 'process_node_objects()' main method, as
        # adding logic inside the default functions is too messy.
        # We may need to return to this later.
        file_ctx = replace(gen_ctx, expr=expr.args["this"])
        stage_ctx = replace(gen_ctx, expr=expr.args["target"])

        file_node = FileNode(gen_ctx=file_ctx, pos_ctx=pos_ctx)
        stage_node = StageNode(gen_ctx=stage_ctx, pos_ctx=pos_ctx)

        yield EdgeToCreate(file_node, stage_node)

    @process.register
    def process_copy(
        self, expr: exp.Copy, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        yield from self.process_column(expr, gen_ctx, pos_ctx)

    @process.register
    def process_column(
        self, expr: exp.Column, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        If the source is actually a Stage, don't try to create a Column.
        """
        query = gen_ctx.query
        if isinstance(query, CopyQuery) and query.is_source_a_stage:
            stage_name: exp.Var = query.get_original_source().this
            parent = StageColumnNode(
                column=expr.name,
                stage=stage_name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(parent, gen_ctx.child_node)
        else:
            yield from super().process_column(expr, gen_ctx, pos_ctx)
