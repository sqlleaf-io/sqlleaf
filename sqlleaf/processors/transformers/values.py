from sqlleaf.processors.transformers.base import BaseQueryTransformer
from sqlleaf.util.iterators import default_column_index_iterator
from sqlglot import exp

class ValuesTransformer(BaseQueryTransformer):
    def transform(self):
        if isinstance(self.statement, exp.Values):
            # Standalone VALUES query: convert to SELECT
            vals = self.statement.expressions[0].expressions
            names = list(default_column_index_iterator(self.query.dialect, vals))
            self.statement = exp.select(*[exp.alias_(v, name) for v, name in zip(vals, names)])
        return self.statement
