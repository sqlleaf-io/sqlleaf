from __future__ import annotations

import typing as t

from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes


class LiteralNode(NodeAttributes):
    KIND = "literal"
    WITH_POSITIONS = True

    def __init__(self, name: t.Any = "", data_type: str = ""):
        super().__init__(name=name, data_type=data_type)

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        super().with_context(gen_ctx)
        return self

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        if (self.expr and self.expr.is_string) or (not self.expr and isinstance(self.name, str)):
            return f'"{self.name.replace("'", "")}"'
        else:
            return self.name
