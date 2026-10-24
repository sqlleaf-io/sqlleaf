from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes


class IntervalNode(NodeAttributes):
    KIND = "interval"
    WITH_POSITIONS = True

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        expr = t.cast(exp.Interval, gen_ctx.expr)
        self.name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        return super().with_context(gen_ctx)

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
