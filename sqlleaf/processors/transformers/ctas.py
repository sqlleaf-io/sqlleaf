"""
CTASTransformer — handles CREATE TABLE AS SELECT (CTAS) statement transformations.
"""
from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer


class CTASTransformer(BaseQueryTransformer):
    """Transformer for CTAS (CREATE TABLE AS SELECT) statements."""

    def transform(self) -> exp.Create:
        stmt = self.statement
        if stmt.expression:
            converted = self._convert_values_to_select(
                stmt.expression, statement=stmt
            )
            if isinstance(converted, exp.Create):
                stmt = converted
                self.statement = stmt
        return stmt
