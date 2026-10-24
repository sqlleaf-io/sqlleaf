from __future__ import annotations

import typing as t
from dataclasses import asdict

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.query import Q, QueryHolder


class NodeAttributes:
    KIND: str = ""
    WITH_POSITIONS: bool = False

    def __init__(
        self,
        name: str = "",
        data_type: str = "",
    ):
        self.expr: exp.Expr | None = None
        self._data_type: exp.DataType | None = None
        self.data_type: str = data_type

        self.name: str = name
        self.kind: str = self.KIND
        self.ctx: PositionContext | None = None

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        self.expr = gen_ctx.expr
        self._data_type = gen_ctx.data_type
        if not self.data_type:
            self.data_type = str(gen_ctx.data_type)
        return self

    def with_positions(self, pos_ctx: PositionContext) -> t.Self:
        self.ctx = pos_ctx
        return self

    @property
    def _emits_positions(self) -> bool:
        return self.WITH_POSITIONS and self.ctx is not None

    # Allows the class to be used a networkx node
    def __hash__(self) -> int:
        return hash(self.full_name)

    def get_data_type(self) -> exp.DataType:
        """Context-only: requires the node to be bound via `with_context`."""
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
        return self._build_name(self.fields(), with_positions=self._emits_positions)

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
        name = "node:" + util.short_sha256_hash(self.full_name)
        return name

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "data_type": self.data_type,
            **self.fields(),
        }
        if self.ctx is not None:
            result["position"] = asdict(self.ctx) if self.WITH_POSITIONS else {}
        return result


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Q,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query
        self.path_idx = path_idx  # The sequence number if a duplicate path

    @property
    def id(self) -> str:
        edge_id = ":".join([
            str(s)
            for s in [
                self.parent.id,
                self.child.id,
                self.path_idx,
            ]
        ])
        return "edge:" + util.short_sha256_hash(edge_id)

    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "source": self.parent.id,
            "target": self.child.id,
            "query": self.query.id,
            "path_index": self.path_idx,
        }
        return result


class GraphAttributes:
    def __init__(self):
        self.queries: list[QueryHolder] = []

    def add_query_to_graph(self, holder: QueryHolder):
        self.queries.append(holder)
