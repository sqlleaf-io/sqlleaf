from __future__ import annotations

import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, TargetInfo


@dataclass(frozen=True)
class TableQueryProperties:
    location: exp.LocationProperty | None

    @classmethod
    def from_expression(cls, expr: exp.Create, dialect: str):
        location = None
        if properties := expr.args.get("properties"):
            location = properties.find(exp.LocationProperty)
        return cls(location=location)


class TableQuery(Query):
    KIND = "table"

    def __init__(self, expr: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        self.properties = TableQueryProperties.from_expression(expr, dialect)

        if self.properties.location:
            location_literal = self.properties.location.this
            source_type = self._determine_expression_type(location_literal, dialect)
            source = SourceInfo(expression=location_literal, type=source_type)
        else:
            source = None

        target = util.get_table(expr.this)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
            skip_type_annotation=True,
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherits: t.List[TableQuery] = []
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(expr, self.target_info.expression, dialect)

    @property
    def location(self) -> exp.LocationProperty | None:
        return self.properties.location

    def is_external(self) -> bool:
        return

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns
