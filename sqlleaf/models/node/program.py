from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class ProgramNode(NodeAttributes):
    KIND = "program"
    WITH_POSITIONS = True

    def __init__(self, name: str = "", program_args: str = "", data_type: str = ""):
        super().__init__(name=name, data_type=data_type)
        self.program_args = program_args

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        copy_stmt = gen_ctx.query.get_original_self().statement
        expr = t.cast(exp.Copy, copy_stmt)

        # TODO: put these inside COPY to prevent lookups to the original query here
        program = expr.args["params"][0].name
        name, args = (program + " ").split(" ", maxsplit=1)
        self.name = name
        self.program_args = args.strip()
        return super().with_context(gen_ctx)

    def with_positions(self, pos_ctx: PositionContext) -> t.Self:
        return super().with_positions(pos_ctx.replace(select_index=0))  # Prevent duplicate nodes

    def fields(self) -> dict[str, str]:
        return {"args": f"'{self.program_args}'"}
