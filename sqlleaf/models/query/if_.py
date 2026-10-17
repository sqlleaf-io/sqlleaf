from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query.base import Query


class IfQuery(Query):
    KIND = "if"

    def __init__(
        self,
        expr: pgexp.PGIf,
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

    @property
    def branches(self) -> list[pgexp.PGIfBranch]:
        return self.statement.args["ifs"]

    @property
    def default_statements(self) -> list[exp.Expr]:
        return self.statement.args.get("default") or []
