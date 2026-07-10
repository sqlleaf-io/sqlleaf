from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo


class SequenceQuery(Query):
    KIND = "sequence"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
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
        self.property = util.find_property(expr, self.target_info.expression, dialect)
