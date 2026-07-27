import sqlglot
from sqlglot import exp

from sqlleaf.processors.transformer.insert import InsertTransformer


class ReplaceTransformer(InsertTransformer):
    """Transformer for REPLACE statements."""

    def transform(self) -> exp.Insert:
        # Transform REPLACE to INSERT
        expression = self.statement.args.get("expression")
        new_sql = f"INSERT {expression.this}" if expression else "INSERT"
        self.statement = sqlglot.parse_one(new_sql, dialect=self.query.dialect)

        return super().transform()
