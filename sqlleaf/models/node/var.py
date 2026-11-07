from __future__ import annotations

from sqlleaf.models.node import NodeAttributes, NodeKind


class VarNode(NodeAttributes):
    KIND = NodeKind.VAR
