from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class UpdateQuery(Query):
    def __init__(
        self,
        expr: exp.Update,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
    ):
        if not table:
            table = util.get_table(expr)
        super().__init__(
            kind="update",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=table,
            object_mapping=object_mapping,
        )
        self.only = table.args.get("only", False) if table else False  # Not available inside a MERGE

    def get_ctes(self):
        with_ = self.statement.args.get("with_", None)
        return with_.expressions if with_ else []
