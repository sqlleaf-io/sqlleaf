from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import OpenQuery

from sqlleaf.processors.transformer.base import BaseQueryTransformer


class OpenTransformer(BaseQueryTransformer):
    """Transformer for OPEN statements in PL/pgSQL."""
    QUERY = OpenQuery

    def transform(self, statement: pgexp.PGOpen) -> pgexp.PGOpen:
        return self._substitute_cursor_parameters(statement)

    def _substitute_cursor_parameters(self, statement: pgexp.PGOpen) -> pgexp.PGOpen:
        """
        Substitute cursor parameters into the referenced cursor.
        """
        return statement
