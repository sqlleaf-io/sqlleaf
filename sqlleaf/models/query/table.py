from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class TableQuery(Query):
    def __init__(
        self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
    ):
        super().__init__(
            kind="table",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(statement.this),
            object_mapping=object_mapping,
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherits: t.List[TableQuery] = []
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(statement, self.get_target(), dialect)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns
