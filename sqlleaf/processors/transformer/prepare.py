import logging

from sqlglot import exp

from sqlleaf.models.query import PrepareQuery
from sqlleaf.processors.transformer import base

logger = logging.getLogger("sqlleaf")


class PrepareTransformer(base.BaseQueryTransformer):
    QUERY = PrepareQuery

    def preprocess(self, statement: exp.Command) -> exp.Expr:
        """
        Override the preprocess() function because we need to select and transform OPEN's cursor expression.
        We do the transformation here, which just lifts the referenced cursor query, transforms it, and assigns
        it back to the OPEN statement.
        """
        return super().preprocess(statement)
