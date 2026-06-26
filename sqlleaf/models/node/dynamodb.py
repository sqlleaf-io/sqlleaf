from __future__ import annotations

import logging

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes

logger = logging.getLogger("sqlleaf")


class DynamoDbNode(NodeAttributes):
    KIND = "column"

    def __init__(
        self,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
        column: str,
    ):
        super().__init__(gen_ctx, pos_ctx, name=column)
        self.path = gen_ctx.expr.name
        self.table_name = self.path.removeprefix("dynamodb://")

    def to_dict(self):
        d = super().to_dict()
        d.update({"table": self.table_name})
        return d

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "kind": "dynamodb",
            "table": self.table_name,
        }

    def friendly_fields(self) -> dict[str, str]:
        return {
            "path": self.path,
        }
