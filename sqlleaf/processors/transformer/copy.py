"""
CopyTransformer — handles COPY statement transformations.
"""

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.models.query import CopyQuery
from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.typing import SqlObjectType
from sqlleaf.util import expression as util


class CopyTransformer(BaseQueryTransformer):
    """Transformer for COPY statements."""
    QUERY = CopyQuery

    def transform(self, statement: exp.Copy) -> exp.Copy:
        self._replace_table_source_with_select(statement)
        return statement

    @BaseQueryTransformer._validate_syntax
    def _replace_table_source_with_select(self, statement: exp.Copy) -> None:
        """
        Replace a table source inside the COPY statement with a SELECT over that table.
        The COPY statement itself is kept.

        COPY fruit.simple (age) TO STDOUT
            -> COPY (SELECT age FROM fruit.simple) TO STDOUT
        COPY fruit.simple FROM STDIN
            -> unchanged as it is a target
        """
        query = self.query
        dialect = query.dialect

        target_columns = query.get_targets()
        if not target_columns:
            raise exception.InvalidQueryError(f"Could not find any columns for expression: {query.target_info.expression}")

        if query.source_info.type != SqlObjectType.TABLE:
            return

        if dialect in ["postgres", "redshift"] and not statement.args["kind"]:
            # COPY X TO STDOUT/STDIN
            source_slot = statement.this
        else:
            source_slot = statement.args["files"][0]

        # Only use the named columns if provided
        named_columns = []
        if isinstance(source_slot, exp.Schema):
            # COPY (name, age) ...
            named_columns = [s.name for s in source_slot.expressions]

        columns = []
        source_cols = {c.name: c for c in query.get_sources()}
        if named_columns:
            # Maintain named column order
            target_cols = [source_cols[name] for name in named_columns if name in source_cols]
        else:
            # Maintain source column order
            target_cols = query.get_sources()

        for c in target_cols:
            column = util.column_def_to_column(c.copy())
            column.set("catalog", "")
            column.set("schema", "")
            column.set("table", "")
            columns.append(column)

        select = exp.select(*columns, dialect=dialect).from_(query.source_info.expression.copy())
        source_slot.replace(select.subquery())
