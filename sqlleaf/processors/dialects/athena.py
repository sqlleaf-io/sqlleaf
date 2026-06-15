from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger

logger = logging.getLogger("sqlleaf")


class AthenaGenerator(BaseGenerator):
    dialect = "athena"

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)
