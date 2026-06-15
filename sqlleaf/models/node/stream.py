from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class StreamNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="stream",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {}

    def get_name(self) -> str:
        return self.name
