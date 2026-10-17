from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query.base import Query


class ExceptionQuery(Query):
    KIND = "exception"

    def __init__(
        self,
        expr: pgexp.PGException,
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
    def whens(self) -> list[pgexp.PGWhen]:
        return self.statement.args.get("whens") or []
