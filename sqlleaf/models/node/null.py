from __future__ import annotations

from sqlglot import exp

from sqlleaf.models.node import NodeAttributes


class NullNode(NodeAttributes):
    KIND = "null"
    WITH_POSITIONS = True

    def fields(self) -> dict[str, str]:
        return {"type": exp.DataType.build("NULL")}

    def get_name(self) -> str:
        return "NULL"
