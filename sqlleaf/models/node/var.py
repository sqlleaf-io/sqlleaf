from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.context import PositionContext
from sqlleaf.models.node import NodeAttributes


class VarNode(NodeAttributes):
    KIND = "var"

    def __init__(self, gen_ctx, pos_ctx: PositionContext):
        super().__init__(gen_ctx, pos_ctx, name=gen_ctx.expr.name, data_type=exp.DataType.build("NULL"))
