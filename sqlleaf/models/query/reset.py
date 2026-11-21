from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.base import DialectConfig
from sqlleaf.models.query.base import Query


class ResetQuery(Query):
    """
    Represents RESET statement.
    """
    KIND = "reset"

    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
            skip_type_annotation=True,
        )

        self.reset_schema()

    def reset_schema(self) -> None:
        self.object_mapping.current_user_schema = DialectConfig(self.dialect).DEFAULT_USER_SCHEMA
