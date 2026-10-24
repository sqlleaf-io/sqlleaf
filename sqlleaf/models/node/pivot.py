from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class _PivotNode(NodeAttributes):
    def __init__(self, data_type: str = ""):
        super().__init__(data_type=data_type)
        self.source: str = ""
        self.target: str = ""

    def set(self, source: str, target: str):
        self.source = source
        self.target = target

    def fields(self) -> dict[str, str]:
        f = {}
        # Keep empty strings as values to match expected test output
        f["source"] = self.source
        f["target"] = self.target
        if self.ctx is not None:
            f["statement"] = str(self.ctx.statement_index)
        return f

    def get_name(self) -> str:
        return ""


class PivotNode(_PivotNode):
    KIND = "pivot"


class UnpivotNode(_PivotNode):
    KIND = "unpivot"
