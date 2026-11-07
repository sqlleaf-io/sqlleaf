from __future__ import annotations

from sqlleaf.models.node import NodeAttributes, NodeKind


class VariableNode(NodeAttributes):
    KIND = NodeKind.VARIABLE
    WITH_POSITIONS = True
