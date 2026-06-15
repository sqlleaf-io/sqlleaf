from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class DeleteQuery(Query):
    def __init__(self, expr: exp.Delete, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="delete",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=expr.this,
            object_mapping=object_mapping,
        )

    def get_ctes(self):
        if "with_" in self.statement.args:
            return self.statement.args["with_"].expressions
        return []
