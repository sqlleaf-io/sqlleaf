import sqlglot
from sqlglot import exp

from sqlleaf.processors.transformer.insert import InsertTransformer


class ReplaceTransformer(InsertTransformer):
    """Transformer for REPLACE statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        # Transform REPLACE to INSERT
        expression = statement.args.get("expression")
        new_sql = f"INSERT {expression.this}" if expression else "INSERT"
        statement = sqlglot.parse_one(new_sql, dialect=self.query.dialect)

        return super().transform(statement)
