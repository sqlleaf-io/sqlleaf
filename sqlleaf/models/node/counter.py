from __future__ import annotations

from sqlleaf.models.node import NodeAttributes, NodeKind


# Represents the source of a 'WITH ORDINALITY' column
class CounterNode(NodeAttributes):
    KIND = NodeKind.COUNTER
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {}

    @property
    def full_name(self) -> str:
        return self.wrap(f"position[{self.ctx.as_str()}]")
