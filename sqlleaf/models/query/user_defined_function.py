from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class UserDefinedFunctionQuery(Query):
    def __init__(
        self,
        dialect,
        statement: exp.Create,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):

        super().__init__(
            kind="udf",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=statement.this.this,
            object_mapping=object_mapping,
        )

        # TODO: support 'default'
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in statement.this.find_all(exp.ColumnDef)
        ]

    @property
    def name(self):
        return ".".join([var for var in [self.schema_name, self.function_name] if var])
