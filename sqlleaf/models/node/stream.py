from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class StreamNode(NodeAttributes):
    KIND = "stream"

    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(gen_ctx, pos_ctx, name=name)

    def fields(self) -> dict[str, str]:
        return {}
