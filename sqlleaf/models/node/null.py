from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class NullNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="null",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name="null",
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": exp.DataType.build("NULL")}

    def get_name(self) -> str:
        return "NULL"
