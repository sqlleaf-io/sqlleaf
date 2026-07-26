from __future__ import annotations

import typing as t

import sqlglot
from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.user_defined_function import _extract_function_info
from sqlleaf.typing import TargetInfo


class ProcedureQuery(Query):
    """
    Holds metadata related to stored procedures.
    """

    KIND = "procedure"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        table = util.get_table(expr)
        target_type = self._determine_expression_type(table, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=table, type=target_type),
        )
        self.schema = table.db
        self.procedure = table.name
        self.signature = str(expr.this)  # e.g. etl.my_proc(v_session_id VARCHAR)

        # TODO: support 'default'
        self.column_defs: t.List[exp.ColumnDef] = expr.this.expressions
        _, _, self.parameters = _extract_function_info(expr)
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": p.name, "type": str(p.type)} for p in self.parameters
        ]
        self.inner_statements = self._extract_inner_statements(expr)

    def _extract_inner_statements(self, expr: exp.Create) -> t.List[exp.Expr]:
        body_expr = expr.args.get("expression")
        if not body_expr:
            return []

        inner_statements = util.iter_inner_statements(body_expr, self.dialect, wrap=True)

        # Filter out statements that do not contain lineage (e.g. END;)
        return [
            stmt for stmt in inner_statements if not isinstance(stmt, (exp.EndStatement, exp.Column, exp.Identifier))
        ]

    @property
    def id(self):
        return "procedure:" + util.short_sha256_hash(self.statement.sql())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "signature": self.signature,
            "args": self.args,
        }

    @property
    def name(self):
        return ".".join([var for var in [self.schema, self.procedure] if var])
