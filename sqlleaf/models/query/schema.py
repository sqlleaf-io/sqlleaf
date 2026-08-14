from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SqlObjectType, TargetInfo


@dataclass(frozen=True)
class SchemaQueryProperties:
    location: str | None

    @classmethod
    def from_expression(cls, expr: exp.Create, dialect: str):
        location = util.get_location_property(expr, dialect)
        return cls(location=location)


class SchemaQuery(Query):
    KIND = "schema"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        source = None
        target = expr.this

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=SqlObjectType.SCHEMA),
        )
        self.properties = SchemaQueryProperties.from_expression(expr, dialect)

    @property
    def location(self) -> str | None:
        return self.properties.location
