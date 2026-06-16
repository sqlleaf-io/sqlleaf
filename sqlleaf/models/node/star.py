from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class StarNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="star",
            data_type=exp.DType.UNKNOWN.into_expr(),
            expr=gen_ctx.expr,
            name="*",
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {}
