from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class SelectQuery(Query):
    KIND = "select"

    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
