from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query


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
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
        )
        self.schema = table.db
        self.procedure = table.name
        self.signature = str(expr.this)  # e.g. etl.my_proc(v_session_id VARCHAR)

        # TODO: support 'default'
        self.column_defs: t.List[exp.ColumnDef] = expr.this.expressions
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in expr.this.find_all(exp.ColumnDef)
        ]

    @property
    def id(self):
        return "procedure:" + util.short_sha256_hash(self.statement_original.sql())

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
