from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class TypeQuery(Query):
    def __init__(
        self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
    ):
        super().__init__(
            kind="type",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(statement),
            object_mapping=object_mapping,
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self._collect()

    def _collect(self) -> None:
        """
        Collect the type's column definitions.
        """
        expression = self.statement.args.get("expression")
        if isinstance(expression, exp.Schema):
            for col_def in expression.expressions:
                if isinstance(col_def, exp.ColumnDef):
                    self.column_defs.append(col_def)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        return {col.name: str(col.kind) for col in self.column_defs}
