from __future__ import annotations

from sqlleaf.models.node import NodeAttributes, NodeKind


# Represents an anonymous series, e.g. the source of a 'WITH ORDINALITY' column or Athena's SEQUENCE()
class SeriesNode(NodeAttributes):
    KIND = NodeKind.SERIES
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {}

    @property
    def full_name(self) -> str:
        return self.wrap(f"position[{self.ctx.as_str()}]")
