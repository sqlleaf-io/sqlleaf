from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo, SqlObjectType


class SelectQuery(Query):
    KIND = "select"

    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source = expr
        source_type = self._determine_expression_type(source, dialect)
        target = self._get_select_into_table(expr)
        target_type = self._determine_expression_type(target, dialect) if target else SqlObjectType.NONE

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type)
        )

    @staticmethod
    def _get_select_into_table(expr: exp.Select) -> exp.Table | None:
        """
        Return the table of a 'SELECT .. INTO <table>'. A MySQL 'INTO @var' assigns a variable, not a table.
        """
        into = expr.args.get("into")
        if into and isinstance(into.this, exp.Table) and not isinstance(into.this.this, exp.Parameter):
            return into.this
        return None

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
