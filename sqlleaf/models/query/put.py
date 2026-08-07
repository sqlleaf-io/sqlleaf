from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo


@dataclass(frozen=True)
class PutQueryParameters:
    file_format: str


class PutQuery(Query):
    KIND = "put"

    def __init__(self, expr: exp.Put, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source = expr.this
        target = expr.args["target"]

        util.rename_if_stage(source, target)

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
            skip_type_annotation=True,
        )
        self.parameters = PutQueryParameters(file_format="TEXT")
