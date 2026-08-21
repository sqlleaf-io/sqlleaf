from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class NullNode(NodeAttributes):
    KIND = "null"
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {"type": "NULL"}

    def get_name(self) -> str:
        return "NULL"
