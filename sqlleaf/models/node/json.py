from __future__ import annotations

import logging
import re
import typing as t

from sqlglot import exp, jsonpath

from sqlleaf.models.context import GeneratorContext
from sqlleaf.models.node import NodeAttributes, NodeKind

logger = logging.getLogger("sqlleaf")


class JsonPathNode(NodeAttributes):
    KIND = NodeKind.JSONPATH

    def __init__(self, selector: str = "", selector_depth: int = 0, data_type: str = ""):
        super().__init__(name=selector, data_type=data_type)
        self.selector = selector
        self.selector_depth = selector_depth

    def with_context(self, gen_ctx: GeneratorContext) -> t.Self:
        if isinstance(gen_ctx.expr, exp.JSONTable):
            # The row path of a JSON_TABLE, e.g. '$[*]' in JSON_TABLE(data, '$[*]' COLUMNS (...))
            self.name = self.selector = gen_ctx.expr.args["path"].name
            self.selector_depth = len(self.json_selectors(gen_ctx.expr))
            return super().with_context(gen_ctx)

        if isinstance(gen_ctx.expr, exp.JSONColumnDef):
            # A JSON_TABLE column, e.g. user_id INT PATH '$.id'. Without a PATH, Postgres defaults to the column name
            path = gen_ctx.expr.args.get("path")
            self.name = self.selector = path.name if path else f'$."{gen_ctx.expr.name}"'
            self.selector_depth = len(self.json_selectors(gen_ctx.expr))
            return super().with_context(gen_ctx)

        expr = t.cast(exp.JSONExtract, gen_ctx.expr)

        selectors = self.json_selectors(expr)
        self.name = self.selector = "".join([str(s) for s in selectors])
        self.selector_depth = len(selectors)

        return super().with_context(gen_ctx)

    @staticmethod
    def json_selectors(expr: exp.JSONExtract | exp.JSONValue | exp.JSONColumnDef | exp.JSONTable) -> list[exp.Expr]:
        """
        Collect all the JSON path elements recursively.
        e.g.
            SELECT my_json -> 'a' -> 'b'
        produces
            ['a', 'b']

        or if we have JSON_VALUE / JSON_QUERY, then the path is a string.
        e.g.
            'lax $.user.age'
        produces the elements of the parsed path:
            ['.user', '.age']
        """
        if isinstance(expr, (exp.JSONValue, exp.JSONColumnDef, exp.JSONTable)) or expr.args.get("json_query"):
            path = expr.args["path"] if isinstance(expr, (exp.JSONValue, exp.JSONColumnDef, exp.JSONTable)) else expr.expression
            path_name = path.name if path else f'$."{expr.name}"'
            # sqlglot keeps the JSON path as a raw string with its mode prefix, so it is parsed here
            parsed = jsonpath.parse(re.sub(r"^(lax|strict)\s+", "", path_name))
            return list(parsed.find_all(exp.JSONPathKey, exp.JSONPathSubscript))

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
