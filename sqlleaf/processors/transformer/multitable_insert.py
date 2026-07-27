"""
MultitableInsertTransformer — handles MultitableInserts statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class MultitableInsertTransformer(BaseQueryTransformer):
    """Transformer for MultitableInserts statements."""

    def transform(self, statement: exp.MultitableInserts) -> exp.MultitableInserts:
        return statement
