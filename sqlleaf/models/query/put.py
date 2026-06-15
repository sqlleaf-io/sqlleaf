from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class PutQuery(Query):
    def __init__(self, expr: exp.Put, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        # TODO: fix types below
        self.source = expr.name
        self.target = expr.args["target"].name

        super().__init__(
            kind="put",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=expr.this,
            object_mapping=object_mapping,
        )
