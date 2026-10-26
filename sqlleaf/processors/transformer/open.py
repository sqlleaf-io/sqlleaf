import typing as t

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import OpenQuery
from sqlleaf.processors.substitutor import substitute
from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.typing import E


class OpenTransformer(BaseQueryTransformer):
    """Transformer for OPEN statements in PL/pgSQL."""
    QUERY = OpenQuery

    def preprocess(self, statement: pgexp.PGOpen) -> exp.Expr:
        """
        Override the preprocess() function because we need to select and transform OPEN's cursor expression.
        We do the transformation here, which just lifts the referenced cursor query, transforms it, and assigns
        it back to the OPEN statement.
        """
        cursor_expr: pgexp.PGOpen = self.query.source()
        cursor_name: exp.Identifier = self.query.target()

        # Fetch the cursor's expression and attach it to this query
        if not cursor_expr:
            cursor_expr = self.query.object_mapping.variables.get_variable(name=cursor_name.name)
            cursor_expr = cursor_expr.copy()
            statement.set("expression", cursor_expr)

        # Add any cursor arguments
        cursor_args = self.query.get_cursor_args()
        if cursor_args:
            cursor_expr = self._substitute_cursor_parameters(cursor_expr, cursor_args)
            statement.set("expression", cursor_expr)

        # Transform the EXECUTE command, e.g. `OPEN curs FOR EXECUTE 'SELECT * FROM source';`
        if isinstance(cursor_expr, pgexp.PGExecute):
            resolved_expr = substitute.resolve_dynamic_sql_command(
                command=cursor_expr.this,
                using=cursor_expr.args.get("using", []),
                object_mapping=self.query.object_mapping,
                dialect=self.query.dialect,
                error_statement=statement,
            )
            statement.set("expression", resolved_expr)
            cursor_expr = resolved_expr

        return super().preprocess(cursor_expr)

    def transform(self, statement: exp.Expr) -> exp.Expr:
        return statement

    def _substitute_cursor_parameters(self, statement: E, cursor_args: list[pgexp.PGCursorArg]) -> E:
        """
        Substitute cursor parameters into the referenced cursor.
        """
        call_args = self.query.statement.args.get("expressions") or []

        if cursor_args:
            return substitute.substitute_cursor_parameters(
                statement, call_args, cursor_args, object_mapping=self.query.object_mapping
            )

        return statement

    def postprocess(self, statement: exp.Expr) -> pgexp.PGOpen:
        """
        Ensure that the OPEN expression returned, not the transformed cursor expression.
        """
        super().postprocess(statement)  # The cursor's statement

        query: OpenQuery = self.query
        if query.source():
            query.source().replace(statement)

        return t.cast(pgexp.PGOpen, self.query.statement)
