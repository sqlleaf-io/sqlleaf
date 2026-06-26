from __future__ import annotations

from sqlleaf.models.node import NodeAttributes


class VariableNode(NodeAttributes):
    KIND = "variable"
    WITH_POSITIONS = True
