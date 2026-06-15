from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class InsertQuery(Query):
    def __init__(
        self,
        expr: exp.Insert,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
    ):
        if not table:
            table = util.get_table(expr)
        super().__init__(
            kind="insert",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=table,
            object_mapping=object_mapping,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
