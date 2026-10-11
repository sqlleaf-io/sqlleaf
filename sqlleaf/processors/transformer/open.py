import typing as t

from sqlglot import exp

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
        """
        cursor_expr: pgexp.PGOpen = statement.args.get("expression")
        # It looks like we need to do the transformation here just to lift the query from the cursor and into
        # this expression because the statement itself may not be associated with the OPEN. For example, it's easier
        # to have the cursor's expression already added to the OPEN so that we can do transformations in place.

    ###########################

        # Transformation 1:
        #  `OPEN curs CURSOR FOR SELECT * FROM source;`
        #  ->
        #  transform `SELECT * FROM source;`

        # Transformation 2:
        #  `curs CURSOR FOR SELECT * FROM source;`
        #  `OPEN curs;`
        #  ->
        #  lift and transform `SELECT * FROM source;`
        if not cursor_expr:
            # I only need to do this one because the other statements will collect transformed queries (inside the collector)
            cursor_expr = self.query.object_mapping.get_variable(name=statement.args["this"].name)
            statement.set("expression", cursor_expr)

        # Transformation 3:
        #  `curs CURSOR (key VARCHAR) FOR SELECT UPPER(key) as name;`
        #  `OPEN curs('abc');`
        #  ->
        #  lift, substitute and transform `SELECT UPPER(key) as name;`

        # Transformation 4:
        #  `OPEN curs CURSOR FOR EXECUTE 'SELECT * FROM source';`
        #  ->
        #  transform `SELECT * FROM source;`

        return super().preprocess(cursor_expr)

    def transform(self, statement: exp.Expr) -> pgexp.PGOpen:
        return self._substitute_cursor_parameters(statement)

    def _substitute_cursor_parameters(self, statement: E) -> E:
        """
        Substitute cursor parameters into the referenced cursor.
        """
        call_args = self.query.statement.args.get("expressions")
        cursor_args = statement.meta.get("cursor_args")

        if call_args and cursor_args:
            return substitute.substitute_cursor_parameters(statement, call_args, cursor_args)

        return statement
    #
    def postprocess(self, statement: exp.Expr) -> pgexp.PGOpen:
        """
        Ensure that the OPEN expression returned, not the transformed cursor expression.
        """
        super().postprocess(statement)  # The cursor's statement

        query: OpenQuery = self.query
        if query.source():
            query.source().replace(statement)

        return t.cast(pgexp.PGOpen, self.query.statement)
