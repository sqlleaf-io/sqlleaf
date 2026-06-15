from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class LiteralNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="literal",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        return self.name.replace("'", '"')
