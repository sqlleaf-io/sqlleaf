from __future__ import annotations

import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes
from sqlleaf.models.query import Query


class ProgramNode(NodeAttributes):
    KIND = "program"
    WITH_POSITIONS = True

    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        pos_ctx = replace(pos_ctx, select_index=0)  # Prevent duplicate nodes
        copy_stmt = gen_ctx.query.get_original_self().statement
        expr = t.cast(exp.Copy, copy_stmt)

        program = expr.args["params"][0].sql()
        name, args = (program + " ").split(" ", maxsplit=1)
        super().__init__(gen_ctx, pos_ctx, name=name)
        self.program_args = args.strip()

    def fields(self) -> dict[str, str]:
        return {"args": f"'{self.program_args}'"}
