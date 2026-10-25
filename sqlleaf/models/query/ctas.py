from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.table import TableQuery
from sqlleaf.typing import SourceInfo, TargetInfo


class CTASQuery(Query):
    KIND = "ctas"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        columns: list[exp.ColumnDef],
        system_columns: list[exp.ColumnDef],
        statement_index: int,
    ):
        source = expr.expression
        if source is None:
            if exec_prop := expr.find(exp.ExecuteAsProperty):
                source = exec_prop.this

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
        self.column_defs: list[exp.ColumnDef] = columns
        self.system_column_defs: list[exp.ColumnDef] = system_columns
        self.inherited_by: list[TableQuery] = []

        self.load_data: bool = True
        if props := expr.args["properties"]:
            if load_data := props.find(exp.WithDataProperty):
                self.load_data: bool = not load_data.args["no"]

        self.property: str = util.find_property(expr, self.target_info.expression, dialect)

    def get_column_defs(self, include_system: bool = False) -> list[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs
