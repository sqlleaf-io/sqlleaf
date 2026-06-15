from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceExprType, TargetExprType


class CopyQuery(Query):
    def __init__(self, expr: exp.Copy, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        # TODO: move these variables/types to SourceExpr/TargetExpr
        self.is_source_a_stage = False
        self.is_target_a_stage = False

        self.source, self.target = self.get_source_and_target(expr, dialect)
        if dialect == "snowflake":
            self.configure_stage(self.source, self.target)

        super().__init__(
            kind="copy",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            target_object=self.target,
            object_mapping=object_mapping,
        )

    def get_source(self):
        # Temp: hacky
        if isinstance(self.statement, exp.Insert):
            return self.statement.expression  # Transformed
        else:
            return self.source  # Original

    def get_original_source(self):
        return self.source

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

    def configure_stage(self, source: SourceExprType, target: TargetExprType):
        """
        Normalize (uppercase) the name if we are a Snowflake stage.
        sqlglot only normalizes columns - see comments in `sqlglot.optimizer.normalize_identifiers()`
        """
        if str(source).startswith("@"):
            self.is_source_a_stage = True
            if not str(source).startswith('@"'):
                source.this.set("this", str(source).upper())

        elif str(target).startswith("@"):
            self.is_target_a_stage = True
            if not str(target).startswith('@"'):
                target.this.set("this", str(target).upper())
