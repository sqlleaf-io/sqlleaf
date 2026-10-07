from sqlglot import exp

from sqlleaf.models.query import ValuesQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer


class ValuesTransformer(BaseQueryTransformer):
    QUERY = ValuesQuery

    def transform(self, statement: exp.Values) -> exp.Values:
        return statement
