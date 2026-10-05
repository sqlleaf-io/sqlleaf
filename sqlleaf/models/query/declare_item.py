from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.dialects.plpgsql import pgexp


class AssignmentQuery(Query):
    KIND = "assignment"

    def __init__(
        self,
        expr: pgexp.PGDeclareItem | exp.PropertyEQ,
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

    def get_key(self) -> exp.Expr:
        return self.statement.this.name

    def get_value(self)-> exp.Expr | None:
        return self.statement.args.get("expression") or self.statement.args.get("query") or exp.Null()
