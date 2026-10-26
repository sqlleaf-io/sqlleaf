"""
DeleteTransformer — handles DELETE statement transformations.
"""

from sqlglot import exp

from sqlleaf.models.query import DeleteQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer


class DeleteTransformer(BaseQueryTransformer):
    """Transformer for DELETE statements."""
    QUERY = DeleteQuery

    def transform(self, statement: exp.Delete) -> exp.Delete:
        self._process_inner_ctes(statement)
        return statement
