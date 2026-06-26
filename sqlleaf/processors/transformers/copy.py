"""
CopyTransformer — handles COPY statement transformations.
"""

from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer
from sqlleaf.util import expression as util


class CopyTransformer(BaseQueryTransformer):
    """Transformer for COPY statements."""

    def transform(self) -> exp.Insert:
        stmt = self._convert_copy_to_insert()
        self.statement = stmt
        return stmt

    @BaseQueryTransformer._validate_syntax
    def _convert_copy_to_insert(self) -> exp.Insert:
        """
        Convert the COPY statement into an INSERT statement.

        COPY INTO <table> FROM @stage
            -> INSERT INTO <table> SELECT * FROM @stage
            => produces lineage: @stage -> N table columns
        COPY INTO @stage FROM <table>
            -> INSERT INTO @stage SELECT * FROM <table>
            => produces lineage: N table columns -> @stage
        """
        query = self.query
        dialect = query.dialect

        target_object = query.get_target_object()
        column_names = [col.name for col in target_object.columns]

        # Transform to a SELECT
        src = query.source_info.expression
        if isinstance(src, exp.Select):
            select = src
        else:
            # Add the column names from the target object
            columns = [util.column_def_to_column(c.copy()) for c in target_object.columns]
            for c in columns:
                c.set("catalog", "")
                c.set("schema", "")
                c.set("table", "")

            # Only use the named columns if provided
            if isinstance(query.statement.this, exp.Schema):
                # COPY (name, age) ...
                named_columns = [s.name for s in query.statement.this.expressions]
                columns = [col for col in columns if col.name in named_columns]
                column_names = named_columns

            select = exp.select(*columns, dialect=dialect).from_(src)

        # Convert the Copy to an Insert
        insert_expr = exp.insert(
            expression=select,
            into=query.get_target_expression(),  # ty: ignore[invalid-argument-type]
            columns=column_names,
            dialect=dialect,
        )
        return insert_expr
