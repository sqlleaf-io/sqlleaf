from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class StarNode(NodeAttributes):
    KIND = "star"
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {}
