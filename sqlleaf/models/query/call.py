from __future__ import annotations

import typing as t
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo, SqlObjectType

if t.TYPE_CHECKING:
    from sqlleaf import mappings


@dataclass(frozen=True)
class CallQueryParameters:
    schema: t.Optional[str]
    procedure: str
    args: t.List[exp.Expr]

    @classmethod
    def from_expression(cls, statement: exp.Command, dialect: str) -> CallQueryParameters:
        # The 'expression' part of the command contains the procedure call
        # e.g., CALL hello('world') -> expression is "hello('world')"
        call_str = statement.args.get("expression").this

        # Parse the call string as a function call
        inner_expr = sqlglot.parse_one(call_str, read=dialect)

        schema = None
        if isinstance(inner_expr, exp.Anonymous):
            procedure_name = inner_expr.this
            args = inner_expr.expressions
        elif isinstance(inner_expr, exp.Column):
            procedure_name = inner_expr.name
            args = []
        elif isinstance(inner_expr, exp.Dot):
            schema = inner_expr.left.name
            if isinstance(inner_expr.right, exp.Anonymous):
                procedure_name = inner_expr.right.this
                args = inner_expr.right.expressions
            else:
                procedure_name = inner_expr.right.name
                args = []
        else:
            procedure_name = call_str
            args = []

        return cls(schema=schema, procedure=procedure_name, args=args)


class CallQuery(Query):
    """
    Holds metadata related to procedure calls (CALL statement).
    """

    KIND = "call"

    def __init__(
        self,
        statement: exp.Command,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        self.properties = CallQueryParameters.from_expression(statement, dialect)

        # We can represent the procedure being called as the target
        target_info = TargetInfo(
            expression=exp.Table(
                this=exp.to_identifier(self.properties.procedure),
                db=exp.to_identifier(self.properties.schema) if self.properties.schema else None,
            ),
            type=SqlObjectType.PROCEDURE,
        )

        super().__init__(
            dialect=dialect,
            statement=statement,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=target_info,
        )

    @property
    def schema(self) -> t.Optional[str]:
        return self.properties.schema

    @property
    def procedure(self) -> str:
        return self.properties.procedure

    @property
    def args(self) -> t.List[exp.Expr]:
        return self.properties.args

    @property
    def name(self):
        return ".".join([var for var in [self.schema, self.procedure] if var])

    @property
    def id(self):
        return "call:" + util.short_sha256_hash(self.statement.sql() + ":" + str(self.statement_index))

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "procedure": self.procedure,
            "schema": self.schema,
            "args": [str(arg) for arg in self.args],
        }
