from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class ProgramNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Copy, gen_ctx.query.statement_original)

        program = expr.args["params"][0].sql()
        name, args = (program + " ").split(" ", maxsplit=1)
        super().__init__(
            kind="program", data_type=exp.DataType.build("UNKNOWN"), expr=gen_ctx.expr, pos_ctx=pos_ctx, name=name
        )
        self.program_args = args.strip()

    def fields(self) -> dict[str, str]:
        return {"args": f"'{self.program_args}'"}
