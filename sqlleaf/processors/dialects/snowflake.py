from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    FileColumnNode,
    StageColumnNode,
)
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger
from sqlleaf.typing import SqlObjectType

logger = logging.getLogger("sqlleaf")


class SnowflakeGenerator(BaseGenerator):
    dialect = "snowflake"

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_put(
        self, expr: exp.Put, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
        - Creates two node: FileColumnNode and StageColumnNode
        """
        source = gen_ctx.query.source_info.expression   called from generator; query is the transformed version
        target = gen_ctx.query.target_info.expression  

        file_format = util.get_file_format(source.name)

        file_ctx = replace(gen_ctx, expr=source)
        stage_ctx = replace(gen_ctx, expr=target)

        file_node = FileColumnNode(
            column="?",
            file_format=file_format,
            file_path=source.name,
            gen_ctx=file_ctx,
            pos_ctx=pos_ctx,
        )
        stage_node = StageColumnNode(
            column="?",
            stage=target,
            gen_ctx=stage_ctx,
            pos_ctx=pos_ctx,
        )

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
        If the source is a Stage, create a StageColumnNode.
        """
        query = gen_ctx.query
        if hasattr(query, "source_info") and query.source_info.type == SqlObjectType.STAGE:   source_info is copied onto the transformed InsertQuery by _build_transformed_query
            stage_name: exp.Var = query.source_info.expression.this  
            parent = StageColumnNode(
                column=expr.name,
                stage=stage_name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(parent, gen_ctx.child_node)
        else:
            yield from super().process_column(expr, gen_ctx, pos_ctx)
