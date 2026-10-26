"""
UnloadTransformer — handles UNLOAD statement transformations.
"""

from sqlglot import exp

from sqlleaf.models.query import UnloadQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer


class UnloadTransformer(BaseQueryTransformer):
    """Transformer for UNLOAD statements."""
    QUERY = UnloadQuery

    def transform(self, statement: exp.Command) -> exp.Command:
        return statement
