from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes


class WindowNode(NodeAttributes):
    KIND = "window"

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        expr = t.cast(exp.Window, gen_ctx.expr.this)
        self.name = util.calculate_function_name(expr, gen_ctx.query.dialect)

        return super().with_context(gen_ctx)

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
