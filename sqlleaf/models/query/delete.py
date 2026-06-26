from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SqlObjectType, TargetInfo


class DeleteQuery(Query):
    KIND = "delete"

    def __init__(self, expr: exp.Delete, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=expr.this, type=SqlObjectType.TABLE),
        )

    def get_ctes(self):
        if "with_" in self.statement.args:
            return self.statement.args["with_"].expressions
        return []
