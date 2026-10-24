from __future__ import annotations

import logging
import typing as t

from sqlglot import exp

from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes

logger = logging.getLogger("sqlleaf")


class JsonPathNode(NodeAttributes):
    KIND = "jsonpath"

    def __init__(self, selector: str = "", selector_depth: int = 0, data_type: str = ""):
        super().__init__(name=selector, data_type=data_type)
        self.selector = selector
        self.selector_depth = selector_depth

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        expr = t.cast(exp.JSONExtract, gen_ctx.expr)

        selectors = self.json_selectors(expr)
        self.name = self.selector = "".join([str(s) for s in selectors])
        self.selector_depth = len(selectors)

        return super().with_context(gen_ctx)

    @staticmethod
    def json_selectors(expr: exp.JSONExtract):
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
