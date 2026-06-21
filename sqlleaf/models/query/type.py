from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo


class TypeQuery(Query):
    KIND = "type"

    def __init__(
        self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
    ):
        source = None
        target = util.get_table(statement)

        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=statement,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self._collect()

    def _collect(self) -> None:
        """
        Collect the type's column definitions.
        """
        expression = self.statement_original.args.get("expression")
        if isinstance(expression, exp.Schema):
            for col_def in expression.expressions:
                if isinstance(col_def, exp.ColumnDef):
                    self.column_defs.append(col_def)
