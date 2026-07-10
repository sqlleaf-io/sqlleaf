from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class SequenceNode(NodeAttributes):
    KIND = "sequence"

    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext, subkind: str = ""):
        super().__init__(gen_ctx, pos_ctx, name=name)
        self.subkind = subkind

    def fields(self) -> dict[str, str]:
        f = {"type": self.data_type}
        if self.subkind:
            f["subkind"] = self.subkind
        return f
