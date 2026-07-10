from __future__ import annotations

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class _PivotNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(gen_ctx, pos_ctx)
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
        f["statement"] = str(self.ctx.statement_index)
        return f

    def get_name(self) -> str:
        return ""


class PivotNode(_PivotNode):
    KIND = "pivot"


class UnpivotNode(_PivotNode):
    KIND = "unpivot"
