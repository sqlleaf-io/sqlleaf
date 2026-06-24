"""
UnloadTransformer — handles UNLOAD statement transformations.
"""
from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer


class UnloadTransformer(BaseQueryTransformer):
    """Transformer for UNLOAD statements."""

    def transform(self) -> exp.Insert:
        stmt = self._convert_unload_to_insert(self.statement)
        self.statement = stmt
        self._validate_values(stmt)
        return stmt

    def _convert_unload_to_insert(self, statement: exp.Select) -> exp.Insert:
        """
        Convert the UNLOAD statement into an INSERT statement.

        UNLOAD ('SELECT * FROM fruit.raw') TO 's3://object-path/name-prefix'
            -> INSERT INTO 's3://object-path/name-prefix' SELECT * FROM fruit.raw
        """
        query = self.query
        table = exp.table_(query.get_target_expression().name)
        insert_expr = exp.insert(
            expression=statement,
            into=table,
            dialect=query.dialect,
        )
        return insert_expr
