"""
UnloadTransformer — handles UNLOAD statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class UnloadTransformer(BaseQueryTransformer):
    """Transformer for UNLOAD statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        return self._convert_unload_to_insert(statement)

    def _convert_unload_to_insert(self, statement: exp.Select) -> exp.Insert:
        """
        Convert the UNLOAD statement into an INSERT statement.

        UNLOAD ('SELECT * FROM fruit.raw') TO 's3://object-path/name-prefix'
            -> INSERT INTO 's3://object-path/name-prefix' SELECT * FROM fruit.raw
        """
        query = self.query
        table = exp.table_(query.target_info.expression.name)
        insert_expr = exp.insert(
            expression=statement,
            into=table,
            dialect=query.dialect,
        )
        return insert_expr
