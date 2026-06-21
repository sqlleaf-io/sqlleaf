from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.table import TableQuery
from sqlleaf.typing import SourceInfo, TargetInfo


class ViewQuery(Query):
    KIND = "view"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        columns: t.List[exp.ColumnDef],
        statement_index: int,
    ):
        source = expr.expression
        target = util.get_table(expr)

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
        self.column_defs: t.List[exp.ColumnDef] = columns
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(expr, self.get_target_expression(), dialect)
