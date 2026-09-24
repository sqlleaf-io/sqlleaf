from __future__ import annotations

import sqlglot
from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo
from sqlleaf.dialects.plpgsql import pgexp


class BlockQuery(Query):
    KIND = "block"

    def __init__(
        self,
        expr: pgexp.PGBlock,
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
