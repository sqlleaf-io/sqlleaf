from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.processors.transformer.expressions import _convert_values_to_select


class ValuesTransformer(BaseQueryTransformer):
    def transform(self, statement: exp.Values) -> exp.Values:
        statement = _convert_values_to_select(self.query, statement, statement)
        return statement
