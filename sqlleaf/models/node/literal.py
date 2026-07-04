from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class LiteralNode(NodeAttributes):
    KIND = "literal"
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        if self.expr.is_string:
            return f'"{self.name.replace("'", "")}"'
        else:
            return self.name
