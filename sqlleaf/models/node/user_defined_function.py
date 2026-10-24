from __future__ import annotations

import typing as t

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes


class UserDefinedFunctionNode(NodeAttributes):
    KIND = "udf"
    WITH_POSITIONS = True

    def __init__(self, name: str = "", schema: str = "", data_type: str = ""):
        super().__init__(name=name, data_type=data_type)
        self.schema = schema

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        schema, function = util.get_udf_name(gen_ctx.expr.this)
        self.schema = schema
        self.name = function
        return super().with_context(gen_ctx)

    def get_name(self) -> str:
        return str(self.name).upper()

    @property
    def friendly_name(self) -> str:
        tokens = [self.schema, self.name]
        name = ".".join([tok for tok in tokens if tok]).upper()
        return self.wrap(name)

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "schema": self.schema.upper() if self.schema else "",
        }
