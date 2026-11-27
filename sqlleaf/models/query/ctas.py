from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.table import TableQuery
from sqlleaf.typing import SourceInfo, TargetInfo
from sqlleaf.util import validate_athena_table_options


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
        validate_athena_table_options(expr, dialect, is_ctas=True)

        source = expr.expression
        if source is None:
            if exec_prop := expr.find(exp.ExecuteAsProperty):
                source = exec_prop.this

        target = util.get_table(expr)
        if not target.db and object_mapping.current_user_schema:
            # Set the schema as the currently selected one
            default_schema = object_mapping.get_current_schema(expr)
            target.set("db", exp.to_identifier(default_schema))
        if target.db and object_mapping.current_catalog and not target.catalog:
            target.set("catalog", exp.to_identifier(object_mapping.current_catalog))

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
        self.column_defs: list[exp.ColumnDef] = [col_def for col_def in columns if not self._is_invisible(col_def)]
        self.invisible_column_defs: list[exp.ColumnDef] = [col_def for col_def in columns if self._is_invisible(col_def)]
        self.system_column_defs: list[exp.ColumnDef] = system_columns
        self.inherited_by: list[TableQuery] = []

        self.load_data: bool = True
        if props := expr.args["properties"]:
            if load_data := props.find(exp.WithDataProperty):
                self.load_data: bool = not load_data.args["no"]

        self.property: str = util.find_property(expr, self.target_info.expression, dialect)

    @staticmethod
    def _is_invisible(col_def: exp.ColumnDef) -> bool:
        return col_def.find(exp.InvisibleColumnConstraint) is not None

    def get_column_defs(self, include_system: bool = False, include_invisible: bool = False) -> list[exp.ColumnDef]:
        column_defs = self.column_defs
        if include_invisible:
            column_defs = column_defs + self.invisible_column_defs
        if include_system:
            column_defs = column_defs + self.system_column_defs
        return column_defs
