"""
InsertTransformer — handles INSERT (and MERGE → INSERT) statement transformations.
"""
from sqlglot import exp

from sqlleaf import util
from sqlleaf.processors.transformers.base import BaseQueryTransformer


class InsertTransformer(BaseQueryTransformer):
    """Transformer for INSERT statements."""

    def transform(self) -> exp.Insert:
        # Note: _convert_table_to_select and FILTER/WHERE removal are performed by
        # _transform_statement before delegating here; self.statement is already clean.
        stmt = self.statement

        stmt = self._convert_insert_defaults_to_values(stmt)
        if stmt.expression:
            stmt_converted = self._convert_values_to_select(stmt.expression, stmt)
            if isinstance(stmt_converted, exp.Insert):
                stmt = stmt_converted

        stmt = self._add_information_from_merge(stmt)
        stmt = self._process_inner_ctes(stmt)

        if isinstance(stmt, exp.Insert):
            self._validate_values(stmt)

        self.statement = stmt
        return stmt

    def _convert_insert_defaults_to_values(self, statement: exp.Insert) -> exp.Insert:
        """
        Transform the query:
            INSERT INTO x DEFAULT VALUES
        into:
            INSERT INTO x VALUES (DEFAULT, DEFAULT)
        and then:
            INSERT INTO x VALUES (NULL, 42)
        according to the table's default column values.
        """
        query = self.query
        child_table = query.get_target_as_table()
        is_default_values = statement.args.get("default", False)
        values = statement.expression

        if not (isinstance(values, exp.Values) or is_default_values):
            return statement

        table_query = query.object_mapping.lookup_table_query(table=child_table)
        if not table_query:
            return statement

        table_columns = table_query.get_column_defs()

        if is_default_values:
            # Transform 'DEFAULT VALUES' into 'VALUES (DEFAULT,)'
            values = exp.Values(
                expressions=[exp.Tuple(expressions=[exp.Var(this="DEFAULT") for _ in table_columns])]
            )
            statement.set("expression", values)
            statement.set("default", False)

        if not isinstance(values, exp.Values):
            return statement

        named_columns = util.get_selected_column_names(statement)

        if not named_columns:
            # Use the associated column names from the mapping
            named_columns = list(table_columns)[: len(values.expressions[0].expressions)]
            named_columns = [n.name for n in named_columns]

        for value_expr in values.expressions:
            if isinstance(value_expr, exp.Tuple):
                for i, tuple_expr in enumerate(value_expr.expressions):
                    if isinstance(tuple_expr, exp.Var) and tuple_expr.name.upper() == "DEFAULT":
                        self._replace_default_with_value(
                            expression=tuple_expr,
                            column_name=named_columns[i],
                            table_columns=table_columns,
                        )
        return statement

    def _add_information_from_merge(self, statement: exp.Insert) -> exp.Insert:
        """
        INSERT branch of _add_information_from_merge.

        Transform a nested INSERT (from a MERGE WHEN NOT MATCHED branch) into a
        fully qualified INSERT … SELECT so it can be processed independently.
        """
        ctx = self._extract_merge_context(statement)
        if ctx is None:
            return statement

        using = ctx["using"]
        returning = ctx["returning"]
        new_ctes = [{"alias": cte.alias_or_name, "as_": cte.this} for cte in ctx["ctes"]]

        # Add the missing information to the INSERT statement
        new_columns = statement.expression.expressions
        new_aliases = statement.this.expressions

        aliases = [exp.alias_(str(col), str(alias)) for col, alias in zip(new_columns, new_aliases)]

        # Build a new SELECT
        new_select = exp.select(*aliases).from_(using)

        insert_expr = exp.insert(
            expression=new_select,
            columns=[col.this for col in statement.this.expressions],
            into=self.query.get_target_expression(),  # ty: ignore[invalid-argument-type]
            dialect=self.query.dialect,
            returning=returning,
        )

        for cte in new_ctes:
            insert_expr = insert_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(insert_expr)
        return insert_expr
