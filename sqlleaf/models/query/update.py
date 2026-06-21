from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo


class UpdateQuery(Query):
    KIND = "update"

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

        if isinstance(expr, exp.OnConflict):
            source = expr
        else:
            source = expr.args["expressions"]
        target = table

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.only = table.args.get("only", False) if table else False  # Not available inside a MERGE

    def get_ctes(self):
        with_ = self.statement_original.args.get("with_", None)
        return with_.expressions if with_ else []
