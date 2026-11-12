from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class UseQuery(Query):
    """
    Represents a USE statement, which selects the current catalog or database.
    """
    KIND = "use"

    def __init__(self, expr: exp.Use, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
            skip_type_annotation=True,
        )

        self.object_mapping.current_database = expr.this.name
