from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.query import Q, QueryHolder


class NodeAttributes:
    KIND: str = ""
    WITH_POSITIONS: bool = False

    def __init__(
        self,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
        name: str | None = "",
    ):
        self.expr: exp.Expr = gen_ctx.expr
        self._data_type: exp.DataType | None = gen_ctx.data_type
        self.data_type: str = str(self._data_type) if self._data_type else ""

        self.name: str = name
        self.kind: str = self.KIND
        self.with_positions: bool = self.WITH_POSITIONS
        self.ctx: PositionContext = pos_ctx

    # Allows the class to be used a networkx node
    def __hash__(self) -> int:
        return hash(self.full_name)

    def get_data_type(self) -> exp.DataType:
        assert self._data_type is not None
        return self._data_type

    def wrap(self, name: str) -> str:
        return f"{self.kind}[{name}]"

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def friendly_fields(self) -> dict[str, str]:
        return {}

    def get_name(self) -> str:
        return self.name

    def _build_name(self, fields_dict: dict[str, str], with_positions: bool = False) -> str:
        """Build a formatted name with fields."""
        fields_dict = fields_dict.copy()
        main_parts = [f"name={self.get_name()}"]

        type_val = fields_dict.pop("type", None)
        if type_val:
            main_parts.append(f"type={type_val}")

        props = " ".join([f"{k}={v}" for k, v in fields_dict.items() if v])
        if props:
            main_parts.append(f"properties=[{props}]")

        content = " ".join(main_parts)
        if with_positions:
            content = f"{content} position=[{self.ctx.as_str()}]"

        return self.wrap(content)

    @property
    def full_name(self) -> str:
        return self._build_name(self.fields(), with_positions=self.with_positions)

    @property
    def friendly_name(self) -> str:
        name = self.get_name()
        fields = self.friendly_fields()

        parts = []
        if name:
            parts.append(name)

        for k, v in fields.items():
            if v:
                parts.append(f"{k}={v}")

        content = " ".join(parts)
        return self.wrap(content)

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
        self.queries: t.List[QueryHolder] = []

    def add_query_to_graph(self, holder: QueryHolder):
        self.queries.append(holder)
