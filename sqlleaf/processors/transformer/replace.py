import sqlglot
from sqlglot import exp

from sqlleaf.processors.transformer.expressions import normalize_all_values
from sqlleaf.processors.transformer.insert import InsertTransformer


class ReplaceTransformer(InsertTransformer):
    """Transformer for REPLACE statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        # Transform REPLACE to INSERT
        expression = statement.args.get("expression")
        new_sql = f"INSERT {expression.this}" if expression else "INSERT"
        statement = sqlglot.parse_one(new_sql, dialect=self.query.dialect)

        # This newly-parsed statement never went through preprocess(), so it hasn't
        # had DEFAULT VALUES expansion or VALUES->SELECT normalization applied yet.
        if isinstance(statement, exp.Insert):
            statement = self._convert_insert_defaults_to_values(statement)
        statement = normalize_all_values(self.query, statement)

        return super().transform(statement)
