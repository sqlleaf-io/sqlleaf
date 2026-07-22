from __future__ import annotations

import sqlglot
from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.insert import InsertQuery


class ReplaceQuery(InsertQuery):
    KIND = "replace"

    def __init__(
        self,
        expr: exp.Command,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        # Transform to Insert temporarily to initialize source/target info
        expression = expr.args.get("expression")
        new_sql = f"INSERT {expression.this}" if expression else "INSERT"
        insert_expr = sqlglot.parse_one(new_sql, dialect=dialect)

        super().__init__(
            expr=insert_expr,
            dialect=dialect,
            object_mapping=object_mapping,
            statement_index=statement_index,
        )
        # Restore the original statement
        self.statement = expr
