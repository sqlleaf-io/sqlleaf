from __future__ import annotations

import logging
import re
import typing as t

import sqlglot
from sqlglot import exp

from sqlleaf import exception, mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo

logger = logging.getLogger("sqlleaf")


class PrepareQuery(Query):
    KIND = "prepare"

    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source, target = self.get_source_and_target_expressions(expr)

        util.qualify_and_annotate(source, dialect, object_mapping)

        source_type = self._determine_expression_type(source, dialect)
        target_type = SqlObjectType.PREPARED_STATEMENT

        # Re-parse the statement now that the source is qualified
        stmt = sqlglot.parse_one(f"PREPARE {target.name} AS {source.sql(dialect=dialect)}", dialect=dialect)

        super().__init__(
            dialect=dialect,
            statement=stmt,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.parameter_count = self._count_parameters(source)

    def _count_parameters(self, source: exp.Expr) -> int:
        """
        Count the number of expected arguments for this prepared statement.
        Positional parameters are $1, $2, etc.
        """
        params = [int(p.name) for p in source.find_all(exp.Parameter) if p.name.isdigit()]
        return max(params) if params else 0

    def get_source_and_target_expressions(self, statement: exp.Command) -> tuple[exp.Expr, exp.Table]:
        """
        Parse a PREPARE statement for Postgres.
        Syntax: PREPARE name AS statement
        """
        expression_name = statement.expression.name

        # Find the 'AS' keyword to split name and statement
        match = re.search(r"\s+AS\s+", expression_name, re.IGNORECASE)
        if not match:
            raise exception.SqlLeafException(message=f"Could not find 'AS' in PREPARE expression: {expression_name}")

        name = expression_name[: match.start()].strip()
        statement_text = expression_name[match.end() :].strip()

        prepared_expr = sqlglot.parse_one(statement_text, dialect="postgres")
        # TODO: coercing to a table is required to be adding to the mapping. This needs to be fixed
        return prepared_expr, exp.to_table(name)
