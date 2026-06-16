from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import PositionContext
from sqlleaf.models.query import Q


class NodeAttributes:
    def __init__(
        self,
        expr: exp.Expr,
        data_type: exp.DataType | None,
        pos_ctx: PositionContext,
        name: str,
        kind: str = "",
        with_positions: bool = False,
    ):
        self.expr = expr
        self.data_type = str(data_type) if data_type else ""
        self._data_type = data_type
        self.name = name
        self.kind = kind
        self.ctx = pos_ctx
        self.with_positions = with_positions

    # Allows the class to be used a networkx node
    def __hash__(self) -> int:
        return hash(self.full_name)

    def get_data_type(self) -> exp.DataType:
        assert self._data_type is not None
        return self._data_type

    def wrap(self, name: str, with_positions: bool = False) -> str:
        if with_positions:
            pos = self.ctx.as_str()
            name = f"{name} {pos}"
        return f"{self.kind}[{name}]"

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def friendly_fields(self) -> dict[str, str]:
        return {}

    def get_name(self) -> str:
        return self.name

    def _build_name(self, fields_dict: dict[str, str], with_positions: bool = False) -> str:
        """Build a formatted name with fields."""
        fields = " ".join([f"{k}={v}" for k, v in fields_dict.items() if v])
        name = f"{self.get_name()} {fields}" if fields else self.get_name()
        return self.wrap(name, with_positions=with_positions)

    @property
    def full_name(self) -> str:
        return self._build_name(self.fields(), with_positions=self.with_positions)

    @property
    def friendly_name(self) -> str:
        return self._build_name(self.friendly_fields())

    @property
    def id(self) -> str:
        # TODO: add correct fields
        fields_dict = self.fields()
        fields = [self.name, type(self.expr).__name__.lower()]
        # Add values from fields_dict to the hash
        for k, v in sorted(fields_dict.items()):
            fields.append(f"{k}={v}")

        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "name": self.name,
            "data_type": self.data_type,
            "kind": self.kind,
        }


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Q,
        select_idx: int,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query

        # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b', 'c')
        self.select_idx = select_idx

        # The position of this edge inside a set of identical edges (e.g. two edges between node A->B).
        # This can occur if the same query is used across multiple files.
        # <TODO: can I rely on the query hash instead?>
        self.path_idx = path_idx

        self.path_id: str | None = None
        self.path_hop: int | None = None

    @property
    def id(self):
        # TODO: get the correct prefix from the parent queries
        prefix = "todo_sp_or_udf"
        edge_id = ":".join([
            str(s)
            for s in [
                prefix,
                self.parent.full_name,
                self.child.full_name,
                self.select_idx,
                self.path_idx,
            ]
        ])
        return "edge:" + util.short_sha256_hash(edge_id)

    def to_dict(self):
        result = {
            "id": self.id,
            "parent": {
                "id": self.parent.id,
                "full_name": self.parent.full_name,
            },
            "child": {
                "id": self.child.id,
                "full_name": self.child.full_name,
            },
            "indices": {
                "select_idx": self.select_idx,
                "path_idx": self.path_idx,
            },
            "query": {"id": self.query.id},
        }
        return result


class GraphAttributes:
    def __init__(self):
        self.queries: t.List[Q] = []

    def add_query_to_graph(self, query: Q):
        self.queries.append(query)
