from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class SequenceNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext, subkind: str = ""):
        super().__init__(
            kind="sequence",
            data_type=exp.DataType.build("INT"),
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )
        self.subkind = subkind

    def fields(self) -> dict[str, str]:
        f = {"type": self.data_type}
        if self.subkind:
            f["kind"] = self.subkind
        return f
