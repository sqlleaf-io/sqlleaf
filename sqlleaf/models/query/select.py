from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class SelectQuery(Query):
    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="select",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(expr),
            object_mapping=object_mapping,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
