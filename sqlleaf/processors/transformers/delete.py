"""
DeleteTransformer — handles DELETE statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer


class DeleteTransformer(BaseQueryTransformer):
    """Transformer for DELETE statements."""

    def transform(self) -> exp.Delete:
        return self._process_inner_ctes(self.statement)
