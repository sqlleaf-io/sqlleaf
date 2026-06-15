from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class TypeQuery(Query):
    def __init__(
        self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
    ):
        super().__init__(
            kind="type",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(statement),
            object_mapping=object_mapping,
        )
