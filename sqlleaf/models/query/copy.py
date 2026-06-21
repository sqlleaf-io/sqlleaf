from __future__ import annotations

import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, exception, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceExprType, TargetExprType, SqlObjectType, TargetInfo, SourceInfo


class CopyQuery(Query):
    KIND = "copy"

    def __init__(self, expr: exp.Copy, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source, target = self.get_source_and_target(expr, dialect)
        if dialect == "snowflake":
            util.rename_if_stage(source, target)

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.qualify_and_annotate()


    def get_source_and_target(self, expr: exp.Copy, dialect: str) -> t.Tuple[SourceExprType, TargetExprType]:
        """
        Determine the source and target expressions of the query.
        """
        if dialect == "postgres":
            # Postgres treats STDOUT and STDIN the same
            if expr.args["kind"]:
                # COPY X FROM STDOUT/STDIN
                source = expr.args["files"][0]
                target = expr.args["this"]
                if isinstance(target, exp.Schema):
                    target = target.this
            else:
                # COPY X TO STDOUT/STDIN
                source = expr.args["this"]
                target = expr.args["files"][0]
                if isinstance(source, exp.Schema):
                    source = source.this

        elif dialect == "snowflake":
            source = expr.args["files"][0]
            target = expr.args["this"]

        # It may be a subquery
        source = source.unnest()
        target = target.unnest()

        return source, target
