from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class IntervalNode(NodeAttributes):
    KIND = "interval"
    WITH_POSITIONS = True

    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Interval, gen_ctx.expr)
        name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        super().__init__(gen_ctx, pos_ctx, name=name)

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
