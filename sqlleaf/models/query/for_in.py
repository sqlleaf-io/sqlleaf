from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query.base import Query


class ForInQuery(Query):
    KIND = "for_in"

    def __init__(
        self,
        expr: pgexp.PGForIn,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
        )

    @property
    def inner_statements(self) -> list[exp.Expr]:
        return self.statement.expressions or []

    @property
    def target(self) -> exp.Identifier | exp.Column | None:
        return self.statement.this

    @property
    def query(self) -> exp.Expr | None:
        return self.statement.args.get("query")

    @property
    def is_range(self) -> bool:
        return self.statement.args.get("start") is not None

    @property
    def start(self) -> exp.Expr | None:
        return self.statement.args.get("start")

    @property
    def end(self) -> exp.Expr | None:
        return self.statement.args.get("end")

    @property
    def step(self) -> exp.Expr | exp.Literal:
        return self.statement.args.get("step") or exp.Literal.number(1)

    @property
    def is_reverse(self) -> bool:
        return bool(self.statement.args.get("reverse"))

    def range_values(self) -> list[int]:
        """
        Return the list of integer values produced by the range iterator.

        For example, given expression "FOR x IN 1..3", we return [1,2,3]

        # TODO: this can return expressions, not just integers
        """
        if self.start is None or self.end is None:
            return []

        start_val = self.start.to_py()
        end_val = self.end.to_py()
        step_val = self.step.to_py()

        # TODO: validate relations between start/end/steps/

        """
        FOR i IN 1..3 LOOP
            -- i will take on the values 1,2,3 within the loop
        END LOOP;

        FOR i IN 1..3 BY 2 LOOP
            -- i will take on the values 1,3 within the loop
        END LOOP;

        FOR i IN REVERSE 3..1 LOOP
            -- i will take on the values 3,2,1 within the loop
        END LOOP;
        """
        if self.is_reverse:
            return list(range(start_val, end_val - 1, -step_val)) if start_val >= end_val else []
        else:
            return list(range(start_val, end_val + 1, step_val)) if start_val <= end_val else []
