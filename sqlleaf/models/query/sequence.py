from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class SequenceQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        super().__init__(
            kind="sequence",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=statement.this,
            object_mapping=object_mapping,
        )
        self.property = util.find_property(statement, self.get_target(), dialect)
