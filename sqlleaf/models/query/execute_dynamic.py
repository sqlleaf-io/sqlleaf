from __future__ import annotations
import typing as t

from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query.base import Query


@dataclass(frozen=True)
class ExecuteDynamicQueryProperties:
    command: exp.Expr | None
    expressions: list[exp.Expr]
    using: list[exp.Expr]
    into: list[exp.Expr]

    @classmethod
    def from_expression(cls, expr: pgexp.PGExecute, dialect: str) -> t.Self:
        """
        EXECUTE command-string [ INTO [STRICT] target ] [ USING expression [, ... ] ];
        """
        # In PGExecute, the command string lives in `this`, not in `expressions`.
        command = expr.this
        expressions = expr.args.get("expressions", [])
        using = expr.args.get("using", [])
        into = expr.args.get("into", [])

        return cls(command=command, expressions=expressions, using=using, into=into)


class ExecuteDynamicQuery(Query):
    KIND = "execute_dynamic"

    def __init__(
        self,
        expr: pgexp.PGExecute,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        self.properties = ExecuteDynamicQueryProperties.from_expression(expr, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None, # TODO: like ExecuteQuery?
        )

    @property
    def expressions(self) -> list[exp.Expr]:
        return self.properties.expressions

    @property
    def command(self) -> exp.Expr | None:
        return self.properties.command

    @property
    def using(self) -> list[exp.Expr]:
        return self.properties.using

    @property
    def into(self) -> list[exp.Expr]:
        return self.properties.into
