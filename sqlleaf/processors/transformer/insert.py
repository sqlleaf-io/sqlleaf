"""
InsertTransformer — handles INSERT (and MERGE → INSERT) statement transformations.
"""

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types

from sqlleaf import util
from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.typing import E


class InsertTransformer(BaseQueryTransformer):
    """Transformer for INSERT statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        # Note: _convert_table_to_select and FILTER/WHERE removal are performed by
        # _transform_statement before delegating here; statement is already clean.
        statement = self._convert_insert_defaults_to_values(statement)
        if statement.expression:
            stmt_converted = self._convert_values_to_select(statement.expression, statement)
            if isinstance(stmt_converted, exp.Insert):
                statement = stmt_converted

        statement = self._add_information_from_merge(statement)
        statement = self._add_information_from_multitable_insert(statement)
        statement = self._process_inner_ctes(statement)

        return statement

    def postprocess(self, statement: E) -> E:
        # TODO: this is a hack to get the types annotated for UDF overloading to work for Inserts.
        #  Revisit proper type annotation so that every query (not just Inserts) has its types populated to enable UDF resolution.
        statement = annotate_types(statement, dialect=self.query.dialect, schema=self.query.object_mapping)
        return super().postprocess(statement)

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
            values = exp.Values(expressions=[exp.Tuple(expressions=[exp.Var(this="DEFAULT") for _ in table_columns])])
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
        target = self.query.target_info.expression

        # Add the missing information to the INSERT statement
        insert_columns = self._extract_insert_columns(statement, target, include_system=False)
        values_lists = self._extract_value_lists(statement.expression)

        if not values_lists:
            return statement

        # Build a new SELECT
        values = values_lists[0]
        aliases = [exp.alias_(val, str(col)) for col, val in zip(insert_columns, values)]
        new_select = exp.select(*aliases).from_(using)

        # 3. Build the standalone INSERT statement
        insert_expr = exp.insert(
            expression=new_select,
            columns=insert_columns,
            into=target,
            dialect=self.query.dialect,
            returning=returning,
        )

        # Add the CTEs
        for cte in ctx["ctes"]:
            insert_expr = insert_expr.with_(alias=cte.alias_or_name, as_=cte.this)

        statement.replace(insert_expr)
        return insert_expr

    def _add_information_from_multitable_insert(self, statement: exp.Insert) -> exp.Insert:
        """
        Reconstruct a standalone INSERT .. SELECT from a MultitableInsert branch.
        """
        ctx = self._extract_multitable_insert_context(statement)
        if ctx is None:
            return statement

        source = ctx["source"]
        target = self.query.target_info.expression

        insert_columns = self._extract_insert_columns(statement, target, include_system=False)
        values_lists = self._extract_value_lists(statement.expression)

        if not values_lists:
            return statement

        selects = []
        for values in values_lists:
            aliases = [exp.alias_(val, str(col)) for col, val in zip(insert_columns, values)]
            new_select = exp.select(*aliases).from_(source.subquery())
            selects.append(new_select)

        new_expression = exp.union(*selects, distinct=False) if len(selects) > 1 else selects[0]

        insert_expr = exp.insert(
            expression=new_expression,
            columns=insert_columns,
            into=target,
            dialect=self.query.dialect,
        )

        statement.replace(insert_expr)
        return insert_expr
