from __future__ import annotations

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query.select import SelectQuery


class PerformQuery(SelectQuery):
    KIND = "perform"

    def __init__(self, expr: pgexp.PGPerform, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(expr=expr, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
