from __future__ import annotations

import typing as t

import sqlglot
from sqlglot import TokenType, exp

from sqlleaf import exception, mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceExprType, TargetExprType


class UnloadQuery(Query):
    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        select_expr, to_location_expr = self._parse_expression(expr)

        super().__init__(
            kind="unload",
            statement=select_expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=to_location_expr,
            object_mapping=object_mapping,
        )
        self.source = select_expr

    def get_source(self):
        # Temp: hacky
        if isinstance(self.statement, exp.Insert):
            return self.statement.expression  # Transformed
        else:
            return self.source  # Original

    def _get_column_defs(
        self,
        target: SourceExprType | TargetExprType,
    ) -> t.List[exp.ColumnDef]:
        """
        TODO: remove this override and use the parent's function.
         This depends on having self.source set up first though.
        """
        source = self.get_source()
        if isinstance(source, exp.Select):
            # TODO: this can't handle functions
            return [
                exp.ColumnDef(this=exp.to_identifier(col.alias_or_name), kind=col.unalias().type)
                for col in source.expressions
            ]
        return super()._get_column_defs(target)

    def _parse_expression(self, statement: exp.Command) -> t.Tuple[exp.Select, exp.Literal]:
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
