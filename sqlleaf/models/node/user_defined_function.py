from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        schema: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = gen_ctx.expr

        super().__init__(
            kind="udf",
            data_type=gen_ctx.data_type,
            expr=expr,
            name=expr.this,
            pos_ctx=pos_ctx,
            with_positions=True,
        )
        self.schema = schema

    def get_name(self) -> str:
        tokens = [self.schema, self.name]
        return ".".join([tok for tok in tokens if tok]).upper()

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}
