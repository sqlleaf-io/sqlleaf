from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes


class ProgramNode(NodeAttributes):
    KIND = "program"

    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        # original_copy_statement cannot be replaced by source_info/target_info here:
        # source_info.expression only holds the stage/file expression, whereas ProgramNode
        # needs the full exp.Copy AST to read query.args["params"] (program name + args).
        copy_stmt = getattr(gen_ctx.query, "original_copy_statement", None) or gen_ctx.query.statement_original
        expr = t.cast(exp.Copy, copy_stmt)

        program = expr.args["params"][0].sql()
        name, args = (program + " ").split(" ", maxsplit=1)
        super().__init__(gen_ctx, pos_ctx, name=name)
        self.program_args = args.strip()

    def fields(self) -> dict[str, str]:
        return {"args": f"'{self.program_args}'"}
