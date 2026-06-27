from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo


class SelectQuery(Query):
    KIND = "select"

    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source = expr
        target = None

        source_type = self._determine_expression_type(source, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=target,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
