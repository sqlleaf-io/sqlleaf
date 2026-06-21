from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class WindowNode(NodeAttributes):
    KIND = "window"

    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Window, gen_ctx.expr.this)
        name = util.calculate_function_name(expr, gen_ctx.query.dialect)

        super().__init__(gen_ctx, pos_ctx, name=name)

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
