from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes

logger = logging.getLogger("sqlleaf")


class JsonPathNode(NodeAttributes):
    KIND = "jsonpath"

    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.JSONExtract, gen_ctx.expr)

        self.selectors = self.json_selectors(expr)
        self.selector = "".join([str(s) for s in self.selectors])
        self.selector_depth = len(self.selectors)

        super().__init__(gen_ctx, pos_ctx, name=self.selector)

    def json_selectors(self, expr: exp.JSONExtract):
        """
        Collect all the JSON path elements recursively.
        e.g.
            SELECT my_json -> 'a' -> 'b'
        produces
            ['a', 'b']
        """
        methods = {
            # Mapping of expression -> attribute getter
            exp.JSONPathKey: None,
            exp.JSONPathSubscript: "this",
        }
        elements = list(expr.expression.find_all(tuple(methods)))

        left = expr.left
        while isinstance(left, (exp.JSONExtract, exp.JSONExtractScalar)):
            elements.extend(list(left.expression.find_all(tuple(methods))))
            left = left.left
        elements.reverse()

        result = []
        for elem in elements:
            getter = methods[type(elem)]
            result.append(getattr(elem, getter) if getter else elem)
        return result

    def fields(self) -> dict[str, str]:
        return {"depth": str(self.selector_depth)}

    def friendly_fields(self) -> dict[str, str]:
        return {}
