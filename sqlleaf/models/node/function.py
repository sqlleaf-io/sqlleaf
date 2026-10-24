from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes


class FunctionNode(NodeAttributes):
    KIND = "function"
    WITH_POSITIONS = True

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        expr = t.cast(t.Union[exp.Binary, exp.Func], gen_ctx.expr)
        if isinstance(expr, exp.Binary):
            name = expr.key
        elif isinstance(expr, exp.Case):
            name = "CASE"
        elif isinstance(expr, exp.Anonymous):
            _, name = util.get_udf_name(expr)
        else:
            name = util.calculate_function_name(expr, gen_ctx.query.dialect)

        self.name = name
        return super().with_context(gen_ctx)

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        return f"{self.name}".upper()
