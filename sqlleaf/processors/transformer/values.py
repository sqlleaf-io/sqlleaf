from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.processors.transformer.expressions import _convert_values_to_select
from sqlleaf.util.iterators import default_column_index_iterator
from sqlglot import exp

class ValuesTransformer(BaseQueryTransformer):
    def transform(self, statement: exp.Values) -> exp.Values:
        statement = _convert_values_to_select(self.query, statement, statement)
        return statement
