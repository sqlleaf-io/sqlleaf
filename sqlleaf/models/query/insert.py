from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo, SqlObjectType


class InsertQuery(Query):
    KIND = "insert"

    def __init__(
        self,
        expr: exp.Insert,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
    ):
        if not table:
            table = util.get_table(expr)

        target = table
        source = expr.expression
        if source:
            source = source.unnest() # Subquery -> Select
        else:
            source = expr.args["source"]

        is_default_values = expr.args.get("default", False)
        if is_default_values:
            source_type = SqlObjectType.VALUES
        elif isinstance(source, exp.Tuple):
            source_type = SqlObjectType.TUPLE
        elif isinstance(source, exp.SetOperation):
            source_type = SqlObjectType.SELECT
        else:
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

    def get_ctes(self):
        return getattr(self.statement_original, "ctes", [])
