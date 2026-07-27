from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.util.iterators import default_column_index_iterator
from sqlglot import exp

class ValuesTransformer(BaseQueryTransformer):
    def transform(self, statement: exp.Values) -> exp.Values:
        if isinstance(statement, exp.Values):
            statement = self._convert_values_to_select(statement, statement)
        return statement
