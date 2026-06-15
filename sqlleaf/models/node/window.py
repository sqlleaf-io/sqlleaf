from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class WindowNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Window, gen_ctx.expr.this)

        super().__init__(
            kind="window",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=util.calculate_function_name(expr, gen_ctx.query.dialect),
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
