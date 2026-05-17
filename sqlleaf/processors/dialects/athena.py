from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate

logger = logging.getLogger("sqlleaf")

class AthenaGenerator(BaseGenerator):
    dialect = "athena"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, processor_ctx, ctx)
