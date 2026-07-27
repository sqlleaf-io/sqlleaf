"""
DeleteTransformer — handles DELETE statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class DeleteTransformer(BaseQueryTransformer):
    """Transformer for DELETE statements."""

    def transform(self, statement: exp.Delete) -> exp.Delete:
        return self._process_inner_ctes(statement)
