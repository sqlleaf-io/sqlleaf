from __future__ import annotations

import sqlglot
from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceInfo, SqlObjectType, TargetInfo


class InsertQuery(Query):
    KIND = "insert"

    def __init__(
        self,
        expr: exp.Insert,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
        # Whether to skip column annotation of types.
        # Used to preserve column types after conversion from COPY to INSERT.
        skip_annotate: bool = False,
    ):
        if not table:
            table = util.get_table(expr)

        target = table
        source = expr.expression
        if source:
            # Subquery(Select) -> Select
            source = source.unnest()
        elif src := expr.args.get("source"):
            # INSERT .. DEFAULT VALUES
            source = src
        else:
            # INSERT .. (VALUES())
            exprs = expr.this.expressions
            if len(exprs) == 1 and (ex := exprs[0]):
                if isinstance(ex, exp.Anonymous) and ex.name.upper() == "VALUES":
                    # sqlglot parses this incorrectly; fix it by re-parsing it to an exp.Values
                    source = sqlglot.parse_one(ex.sql(dialect=dialect), dialect=dialect)
                    expr.set("expression", source)
                    [e.pop() for e in (expr.this.expressions or [])]

        # Set the correct source type. Hacky, but works for now
        is_default_values = expr.args.get("default", False)
        if is_default_values:
            source_type = SqlObjectType.VALUES
        elif isinstance(source, exp.Tuple):
            source_type = SqlObjectType.TUPLE
        elif isinstance(source, exp.SetOperation):
            source_type = SqlObjectType.SELECT
        else:
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

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])
