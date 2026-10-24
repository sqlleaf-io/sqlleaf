from __future__ import annotations

import logging
import typing as t

from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes

logger = logging.getLogger("sqlleaf")


class DynamoDbNode(NodeAttributes):
    KIND = "column"

    def __init__(
        self,
        column: str,
        table_name: str = "",
        path: str = "",
        data_type: str = "",
    ):
        super().__init__(name=column, data_type=data_type)
        self.table_name = table_name
        self.path = path

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        self.path = gen_ctx.expr.name
        self.table_name = self.path.removeprefix("dynamodb://")
        return super().with_context(gen_ctx)

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
