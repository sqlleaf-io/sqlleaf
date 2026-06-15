from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import PositionContext
from sqlleaf.models.node import NodeAttributes


class VarNode(NodeAttributes):
    def __init__(self, gen_ctx, pos_ctx: PositionContext):
        super().__init__(
            kind="var",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name=gen_ctx.expr.name,
            pos_ctx=pos_ctx,
        )
