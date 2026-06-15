from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class VariableNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="variable",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name="todo",
            pos_ctx=pos_ctx,
        )
