from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.processors.transformer.expressions import normalize_values


class ValuesTransformer(BaseQueryTransformer):
    def transform(self, statement: exp.Values) -> exp.Values:
        statement = normalize_values(self.query, statement)
        return statement
