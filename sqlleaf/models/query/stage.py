from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo


class StageQuery(Query):
    KIND = "stage"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        source = None
        target = util.get_table(expr)

        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
        )

        self.column_defs: t.List[exp.ColumnDef] = []
        # Needed due to a bug in sqlglot. Never access the table name via print()!
        #  as it prints double-double quotes
        stage_name = str(self.get_target_expression().this)
        self.get_target_expression().this.set("this", "@" + stage_name)
        self.get_target_expression().this.set("quoted", False)

        self.property = util.find_property(expr, self.get_target_expression(), dialect)

