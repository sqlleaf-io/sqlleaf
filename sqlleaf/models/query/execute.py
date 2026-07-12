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
    name: str
    args: t.List[exp.Expr]

    @classmethod
    def from_expression(cls, expr: exp.Command, dialect: str):
        expression_name = expr.expression.name
        parsed = sqlglot.parse_one(expression_name, read=dialect)

        if isinstance(parsed, exp.Anonymous):
            name = parsed.this
            args = parsed.expressions
        else:
            name = parsed.name
            args = []

        return cls(name=name, args=args)


class ExecuteQuery(Query):
    KIND = "execute"

    def __init__(
        self,
        expr: exp.Command,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        self.parameters = ExecuteQueryParameters.from_expression(expr, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=exp.to_table(self.parameters.name), type=SqlObjectType.PREPARED_STATEMENT),
        )
