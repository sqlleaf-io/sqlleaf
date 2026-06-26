from __future__ import annotations

import typing as t
from dataclasses import dataclass

import sqlglot
from sqlglot import TokenType, exp

from sqlleaf import exception, mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceExprType, TargetExprType, TargetInfo, SourceInfo, SqlObjectType


@dataclass(frozen=True)
class UnloadQueryParameters:
    file_format: str


class UnloadQuery(Query):
    KIND = "unload"

    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source, target = self.get_source_and_target_expressions(expr)

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=source,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.parameters = UnloadQueryParameters(file_format="UNKNOWN")
        self.qualify_and_annotate()

    def get_source_and_target_expressions(self, statement: exp.Command) -> t.Tuple[exp.Select, exp.Literal]:
        """
        Parse an UNLOAD statement for Redshift.
        We parse this ourselves due to missing support in sqlglot.
        """
        # Syntax: "UNLOAD ('SELECT ...') TO ..."
        expected_tokens = [TokenType.L_PAREN, TokenType.STRING, TokenType.R_PAREN, TokenType.VAR, TokenType.STRING]
        actual_tokens = sqlglot.tokenize(statement.expression.name, dialect="redshift")

        # Basic validation - ensure the token types match
        for i in range(len(expected_tokens)):
            if expected_tokens[i] != actual_tokens[i].token_type:
                # This may be incorrect! Use the parser instead once available.
                raise exception.SqlLeafException(
                    message=f"Invalid syntax for UNLOAD expression: {statement.sql(dialect='redshift')}"
                )

        select_expr = sqlglot.parse_one(actual_tokens[1].text, dialect="redshift")
        if not isinstance(select_expr, exp.Select):
            raise exception.SqlLeafException(
                message=f"Invalid expression inside UNLOAD. Expected SELECT "
                f"but got: {select_expr.sql(dialect='redshift')}"
            )

        to_location = actual_tokens[4].text
        return select_expr, t.cast(exp.Literal, exp.convert(to_location))
