from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class StreamNode(NodeAttributes):
    KIND = "stream"

    def __init__(self, name: str, data_type: str = ""):
        super().__init__(name=name, data_type=data_type)

    def fields(self) -> dict[str, str]:
        return {}
