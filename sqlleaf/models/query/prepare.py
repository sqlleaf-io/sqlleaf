from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

import sqlglot
from sqlglot import TokenType, exp

from sqlleaf import exception, mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo

logger = logging.getLogger("sqlleaf")


class PrepareQuery(Query):
    KIND = "prepare"

    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source, target = self.get_source_and_target_expressions(expr)

        source_type = self._determine_expression_type(source, dialect)
        target_type = SqlObjectType.NONE

        super().__init__(
            dialect=dialect,
            statement=source,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.qualify_and_annotate()

    def get_source_and_target_expressions(self, statement: exp.Command) -> t.Tuple[exp.Expr, exp.Table]:
        """
        Parse a PREPARE statement for Postgres.
        Syntax: PREPARE name AS statement
        """
        expression_name = statement.expression.name
        tokens = sqlglot.tokenize(expression_name, dialect="postgres")
        name = tokens[0].text

        # Find the statement after the 'AS' token and re-parse it.
        if tokens[1].text.lower() != "as":
             raise exception.SqlLeafException(message=f"Could not find 'AS' in PREPARE expression: {expression_name}")

        statement_text = " ".join(tok.text for tok in tokens[2:])

        try:
            select_expr = sqlglot.parse_one(statement_text, dialect="postgres")
        except Exception as e:
            raise exception.SqlLeafException(message=f"Could not parse statement inside PREPARE: {e}")

        return select_expr, exp.to_table(name)
