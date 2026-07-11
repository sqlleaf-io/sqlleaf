from __future__ import annotations

import typing as t
from dataclasses import dataclass

import sqlglot
from sqlglot import TokenType, exp

from sqlleaf import exception, mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SqlObjectType, TargetInfo


@dataclass(frozen=True)
class ExecuteQueryParameters:
    name: exp.Literal


class ExecuteQuery(Query):
    KIND = "execute"

    def __init__(
        self,
        expr: exp.Command,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        target = expr.expression.name
        self.parameters = ExecuteQueryParameters(name=target)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=target,type=SqlObjectType.PREPARED_STATEMENT),
        )
