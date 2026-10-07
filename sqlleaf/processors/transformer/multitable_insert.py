"""
MultitableInsertTransformer — handles MultitableInserts statement transformations.
"""

from sqlglot import exp

from sqlleaf.models.query import MultitableInsertQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer


class MultitableInsertTransformer(BaseQueryTransformer):
    """Transformer for MultitableInserts statements."""
    QUERY = MultitableInsertQuery

    def transform(self, statement: exp.MultitableInserts) -> exp.MultitableInserts:
        return statement
