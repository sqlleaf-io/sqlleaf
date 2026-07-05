from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo


class MultitableInsertQuery(Query):
    KIND = "multitableinserts"

    def __init__(
        self,
        expr: exp.MultitableInserts,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        source = expr.args["source"]
        source_type = SqlObjectType.SELECT

        # For multi-table inserts, the target is actually multiple tables,
        # but the base Query model expects a single TargetInfo.
        # We'll use the first one or a dummy for the parent query.
        # The children will have the actual target info.
        # TODO: fix this.
        target = expr.expressions[0].this.this

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=SqlObjectType.TABLE),
        )

    def get_ctes(self) -> t.List[exp.CTE]:
        return getattr(self.statement, "ctes", [])
