from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class ValuesTransformer(BaseQueryTransformer):
    def transform(self, statement: exp.Values) -> exp.Values:
        return statement
