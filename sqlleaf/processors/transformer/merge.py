"""
MergeTransformer — handles MERGE statement transformations.
"""

from sqlglot import exp

from sqlleaf.models.query import MergeQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer


class MergeTransformer(BaseQueryTransformer):
    """Transformer for MERGE statements."""
    QUERY = MergeQuery

    def transform(self, statement: exp.Merge) -> exp.Merge:
        return self._process_inner_ctes(statement)
