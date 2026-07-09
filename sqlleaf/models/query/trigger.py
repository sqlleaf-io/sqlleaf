from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SqlObjectType, TargetInfo


class TriggerQuery(Query):
    KIND = "trigger"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        """
        Example:
            CREATE TRIGGER before_fruit_insert
                BEFORE INSERT ON fruit.processed
                FOR EACH ROW
                EXECUTE FUNCTION check_fruit('apple');
        """
        properties = expr.args["properties"].expressions[0]
        target = expr.this
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=target, type=SqlObjectType.TABLE),
        )
        self.name = expr.name  # before_fruit_insert
        self.table = properties.args["table"]  # Table(fruit.processed)
        self.timing = properties.args["timing"]  # BEFORE
        self.events = properties.args["events"]  # [TriggerEvent(INSERT)]
        self.execute = properties.args["execute"].this  # Anonymous(check_fruit())
        self.execute_args = self.execute.expressions  # [Literal(apple)]
