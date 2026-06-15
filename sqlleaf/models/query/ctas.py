from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.table import TableQuery


class CTASQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        columns: t.List[exp.ColumnDef],
        statement_index: int,
    ):
        super().__init__(
            kind="ctas",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(statement),
            object_mapping=object_mapping,
        )
        self.column_defs: t.List[exp.ColumnDef] = columns
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherited_by: t.List[TableQuery] = []

        self.with_data: bool = True
        if props := statement.args["properties"]:
            if with_data := props.find(exp.WithDataProperty):
                self.with_data: bool = not with_data.args["no"]

        self.property: str = util.find_property(statement, self.get_target(), dialect)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns
