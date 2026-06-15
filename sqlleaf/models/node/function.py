from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class FunctionNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(t.Union[exp.Binary, exp.Func], gen_ctx.expr)

        if isinstance(expr, exp.Binary):
            name = expr.key
        else:
            name = util.calculate_function_name(expr, gen_ctx.query.dialect)

        super().__init__(
            kind="function",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        return f"{self.name}".upper()
