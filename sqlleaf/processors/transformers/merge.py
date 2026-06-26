"""
MergeTransformer — handles MERGE statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer


class MergeTransformer(BaseQueryTransformer):
    """Transformer for MERGE statements."""

    def transform(self) -> exp.Merge:
        return self._process_inner_ctes(self.statement)
