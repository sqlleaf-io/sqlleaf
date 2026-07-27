"""
CTASTransformer — handles CREATE TABLE AS SELECT (CTAS) statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class CTASTransformer(BaseQueryTransformer):
    """Transformer for CTAS (CREATE TABLE AS) statements."""

    def transform(self, statement: exp.Create) -> exp.Create:
        if statement.expression:
            statement = self._convert_substituted_table_to_select(statement)
            converted = self._convert_values_to_select(statement.expression, statement=statement)
            if isinstance(converted, exp.Create):
                statement = converted
        return statement

    def _convert_substituted_table_to_select(self, statement: exp.Create) -> exp.Create:
        """
        Convert "CREATE TABLE w AS TABLE x" to "CREATE TABLE w AS SELECT * FROM x".

        The former statement is not actually valid SQL; it only appears after the substitution functions have
        run over an EXECUTE, i.e.:
            PREPARE stmt AS TABLE x;
            CREATE TABLE w AS EXECUTE stmt;
            ->
            CREATE TABLE w AS TABLE x;
            ->
            CREATE TABLE w AS SELECT * FROM x;
        This is handled separately from _convert_table_as_select(), which handles all other TABLE cases.
        """
        expr = statement.expression
        if self.query.dialect == "postgres" and isinstance(expr, exp.Alias):
            if expr.this.name.upper() == "TABLE":
                expr.pop()
                statement.set("expression", exp.select("*").from_(expr.alias))
        return statement
