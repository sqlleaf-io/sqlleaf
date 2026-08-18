from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import FileColumnNode
from sqlleaf.processors.generator.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger

logger = logging.getLogger("sqlleaf")


class AthenaGenerator(BaseGenerator):
    dialect = "athena"

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
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

        file_format_property = gen_ctx.query.statement.args["properties"].find(exp.FileFormatProperty)
        file_format = file_format_property.this.name if file_format_property else ""

        column_node = self.create_node(FileColumnNode(
            column=child_node.name,
            file_format=file_format,
            file_path=location.name,
            gen_ctx=gen_ctx,
            pos_ctx=pos_ctx,
        ))

        yield EdgeToCreate(column_node, child_node)
