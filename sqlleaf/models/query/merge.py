from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo


class MergeQuery(Query):
    KIND = "merge"

    def __init__(self, expr: exp.Merge, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source = None
        target = expr.this

        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
        )

    def get_ctes(self):
        return getattr(self.statement_original, "ctes", [])
