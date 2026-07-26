from sqlleaf.processors.transformers.base import BaseQueryTransformer
from sqlleaf.util.iterators import default_column_index_iterator
from sqlglot import exp

class ValuesTransformer(BaseQueryTransformer):
    def transform(self):
        if isinstance(self.statement, exp.Values):
            self.statement = self._convert_values_to_select(self.statement, self.statement)
        return self.statement
