from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    FileColumnNode,
    StageColumnNode,
)
from sqlleaf.processors.generator.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger
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
        source = gen_ctx.query.source_info.expression
        target = gen_ctx.query.target_info.expression

        file_format = gen_ctx.query.get_original_self().parameters.file_format

        file_ctx = gen_ctx.replace(expr=source)
        stage_ctx = gen_ctx.replace(expr=target)

        stage_query = gen_ctx.query.object_mapping.get_table_or_stage(table=target, raise_on_missing=False)

        file_node = self.create_node(FileColumnNode(
            column="?",
            file_format=file_format,
            file_path=source.name,
            gen_ctx=file_ctx,
            pos_ctx=pos_ctx,
        ))
        stage_node = self.create_node(StageColumnNode(
            column="?",
            stage=target,
            gen_ctx=stage_ctx,
            pos_ctx=pos_ctx,
            path=stage_query.path,
        ))

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
        if hasattr(query, "source_info") and query.source_info.type == SqlObjectType.STAGE:
            stage_expr = query.source_info.expression
            stage_name: exp.Var = stage_expr.this
            stage_query = query.object_mapping.get_table_or_stage(table=stage_expr, raise_on_missing=False)
            stage_path = stage_query.path

            parent = self.create_node(StageColumnNode(
                column=expr.name,
                stage=stage_name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
                path=stage_path,
            ))
            yield EdgeToCreate(parent, gen_ctx.child_node)
        else:
            yield from super().process_column(expr, gen_ctx, pos_ctx)
