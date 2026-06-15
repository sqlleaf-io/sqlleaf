from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


class StageQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        super().__init__(
            kind="stage",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=util.get_table(statement),
            object_mapping=object_mapping,
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        # Needed due to a bug in sqlglot. Never access the table name via print()!
        #  as it prints double-double quotes
        stage_name = str(self.get_target().this)
        self.get_target().this.set("this", "@" + stage_name)
        self.get_target().this.set("quoted", False)

        self.property = util.find_property(statement, self.get_target(), dialect)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs
