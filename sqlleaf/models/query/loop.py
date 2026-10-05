from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.dialects.plpgsql import pgexp


class LoopQuery(Query):
    KIND = "loop"

    def __init__(
        self,
        expr: pgexp.PGLoop,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
        )

    @property
    def inner_statements(self) -> list[exp.Expr]:
        return self.statement.args["body"]
