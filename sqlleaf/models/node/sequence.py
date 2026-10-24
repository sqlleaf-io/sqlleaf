from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class SequenceNode(NodeAttributes):
    KIND = "sequence"

    def __init__(self, name: str, subkind: str = "", data_type: str = ""):
        super().__init__(name=name, data_type=data_type)
        self.subkind = subkind

    def fields(self) -> dict[str, str]:
        f = {"type": self.data_type}
        if self.subkind:
            f["subkind"] = self.subkind
        return f
