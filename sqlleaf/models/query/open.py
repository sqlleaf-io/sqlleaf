from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.dialects.plpgsql import pgexp


class OpenQuery(Query):
    KIND = "open"

    def __init__(
        self,
        expr: pgexp.PGOpen,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int | str,
    ):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
        )

    def source(self)-> exp.Expr | None:
        return self.statement.args.get("expression")

    def target(self)-> exp.Identifier:
        return self.statement.this

    def get_source_expression(self) -> exp.Expr | None:
        return self.source()

    def get_target_expression(self) -> exp.Identifier:
        return self.target()
