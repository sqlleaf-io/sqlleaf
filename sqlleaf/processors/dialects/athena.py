from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate

logger = logging.getLogger("sqlleaf")


class AthenaGenerator(BaseGenerator):
    dialect = "athena"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)
