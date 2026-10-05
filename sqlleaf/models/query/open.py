from __future__ import annotations

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.dialects.plpgsql import pgexp


class OpenQuery(Query):
    KIND = "open"

    def __init__(
        self,
        expr: pgexp.PGOpen,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int | str,
    ):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
        )
