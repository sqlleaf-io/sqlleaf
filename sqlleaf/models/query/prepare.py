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
        source, target = self.get_source_and_target_expressions(expr, dialect)
        self._ensure_no_local_variables(source, target, object_mapping)

        util.qualify_and_annotate(source, dialect, object_mapping)

        source_type = self._determine_expression_type(source, dialect)
        target_type = SqlObjectType.PREPARED_STATEMENT

        # Re-parse the statement now that the source is qualified
        source_sql = source.sql(dialect=dialect)
        if dialect == "mysql":
            prepare_sql = f"PREPARE {target.name} FROM {exp.Literal.string(source_sql).sql(dialect=dialect)}"
        else:
            prepare_sql = f"PREPARE {target.name} AS {source_sql}"
        stmt = sqlglot.parse_one(prepare_sql, dialect=dialect)

        super().__init__(
            dialect=dialect,
            statement=stmt,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.parameter_count = self._count_parameters(source)

    @staticmethod
    def _ensure_no_local_variables(
        source: exp.Expr, target: exp.Table, object_mapping: mappings.ObjectMapping
    ) -> None:
        """
        A statement prepared inside a stored program cannot refer to its parameters or local variables
        because they go out of scope when the program ends. User-defined variables (@var) must be used instead.
        """
        if len(object_mapping.variables.scopes) == 1:
            return

        for column in source.find_all(exp.Column):
            if column.table:
                continue
            if object_mapping.variables.get_variable(column.name, raise_on_missing=False) is not None:
                raise exception.InvalidQueryError(
                    f"Prepared statement '{target.name}' cannot refer to the stored program variable '{column.name}'. "
                    "Use a user-defined variable instead."
                )

    @staticmethod
    def _count_parameters(source: exp.Expr) -> int:
        """
        Count the number of expected arguments for this prepared statement.
        Positional parameters are $1, $2, etc.
        """
        params = [int(p.name) for p in source.find_all(exp.Parameter) if p.name.isdigit()]
        return max(params) if params else 0

    def get_source_and_target_expressions(self, statement: exp.Command, dialect: str) -> tuple[exp.Expr, exp.Table]:
        """
        Parse a PREPARE statement for Postgres or MySQL.
        Postgres syntax: PREPARE name AS statement
        MySQL syntax: PREPARE name FROM preparable_stmt
        """
        if dialect == "mysql":
            return self._get_mysql_source_and_target_expressions(statement)

        # The below is for Postgres
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

    @staticmethod
    def _get_mysql_source_and_target_expressions(statement: exp.Command) -> tuple[exp.Expr, exp.Table]:
        """
        Parse a PREPARE statement for MySQL. The tokens are: name, FROM, quoted statement.
        """
        name_token, _, statement_token = sqlglot.tokenize(statement.expression.name, dialect="mysql")

        prepared_expr = sqlglot.parse_one(statement_token.text, dialect="mysql")
        return prepared_expr, exp.to_table(name_token.text)
