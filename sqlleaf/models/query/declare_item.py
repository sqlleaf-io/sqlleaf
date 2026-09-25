from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.dialects.plpgsql import pgexp


class DeclareItemQuery(Query):
    KIND = "declare_item"

    def __init__(
        self,
        expr: pgexp.PGDeclareItem,
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

    def get_value(self)-> exp.Expr | None:
        return self.statement.args.get("expression") or exp.Null()
