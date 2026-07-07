from __future__ import annotations

import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo


@dataclass(frozen=True)
class StageQueryParameters:
    property: str
    path: str

    @classmethod
    def from_expression(
        cls, expr: exp.Create, source_info: SourceInfo, target_info: TargetInfo, dialect: str
    ) -> StageQueryParameters:
        property = util.find_property(expr, target_info.expression, dialect)

        path = ""
        # Get the URL
        if props := expr.args.get("properties"):
            for prop in props.expressions:
                if isinstance(prop, exp.Property) and prop.name.upper() == "URL":
                    path = prop.args["value"].this
                    break
        return cls(property=property, path=path)


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
        target.this.set("this", "@" + str(target.this))
        target.this.set("quoted", False)

        self.properties = StageQueryParameters.from_expression(
            self.statement, self.source_info, self.target_info, dialect
        )

    @property
    def path(self) -> str:
        return self.properties.path
