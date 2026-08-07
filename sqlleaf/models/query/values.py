from sqlglot import exp

from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo


class ValuesQuery(Query):
    KIND = "values"

    def __init__(self, expr: exp.Values, dialect: str, object_mapping, statement_index: int):
        source_info = SourceInfo(expression=expr, type=SqlObjectType.VALUES)
        target_info = TargetInfo(expression=None, type=SqlObjectType.NONE)
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source_info,
            target_info=target_info,
        )
