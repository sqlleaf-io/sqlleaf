"""
UpdateTransformer — handles UPDATE (and MERGE → UPDATE, ON CONFLICT) statement transformations.
"""

from sqlglot import exp

from sqlleaf import exception
from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.processors.transformer.expressions import normalize_values


class UpdateTransformer(BaseQueryTransformer):
    """Transformer for UPDATE statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        statement = self._convert_on_conflict_to_update(statement)
        if isinstance(statement, (exp.Insert, exp.Update)):
            statement = self._add_information_from_merge(statement)
        if isinstance(statement, exp.Update):
            statement = self._convert_update_defaults_to_values(statement)
            statement = self._convert_update_to_insert(statement)
        if isinstance(statement, (exp.Insert, exp.Merge, exp.Update, exp.Delete)):
            statement = self._process_inner_ctes(statement)
        return statement

    def _convert_on_conflict_to_update(self, statement: exp.OnConflict | exp.Update) -> exp.Update:
        """
        Convert the 'DO UPDATE' in:
            INSERT INTO <table> as t
            ON CONFLICT
            DO UPDATE SET name = EXCLUDED.name
        to:
            UPDATE <table> AS t
            SET name = name
        so that the expression has the correct columns/values.
        """
        if not isinstance(statement, exp.OnConflict):
            return statement

        # Note: this holder's `preprocess()`/`normalize_all_values()` only walks
        # descendants of `statement` (the OnConflict node itself), so it never sees the
        # sibling VALUES living under the ancestor Insert/Create's `.expression` in this
        # holder's own copy of the tree. That conversion must still happen here.
        parent_insert_expr = None
        values_alias_name: str | None = None
        parent = statement.parent
        parent_expr = statement.parent.expression

        update_expr = exp.update(table=self.query.get_target_as_table())
        parent_table = parent_expr.args.get("from_", None)
        if parent_table:
            update_expr = update_expr.from_(parent_table.this)

        if isinstance(parent_expr, exp.Values):
            # Capture the VALUES alias (used in MySQL: VALUES (...) AS <alias>) before we rewrite it
            alias_expr = parent_expr.args.get("alias")

            if alias_expr is not None:
                # exp.TableAlias typically exposes the alias via `.alias`; fallback to `.name` if needed
                values_alias_name = alias_expr.alias_or_name

            parent_insert_expr = normalize_values(self.query, parent)
            statement = parent_insert_expr.args["conflict"]

        elif isinstance(parent_expr, exp.Select):
            parent_insert_expr = parent


        # Rewrite the expressions in the UPDATE
        for eq_expr in list(statement.expressions):
            right_expr = eq_expr.right

            if self.query.dialect == "mysql" and isinstance(right_expr, exp.Anonymous) and right_expr.name.upper() == "VALUES":
                # Replace the VALUES() expression with its associated expression in the SELECT.
                # The inner column is a reference to the SELECT expression in the INSERT list, not the column itself.
                # e.g. INSERT INTO users (id, name) SELECT 'a', 'b' ... UPDATE SET name = VALUES(name)
                # would replace VALUES(name) with 'b'
                values_col = right_expr.expressions[0].name
                column_names = self._extract_insert_columns(parent, self.query.target_info.expression, include_system=False)
                if values_col not in column_names:
                    raise exception.MappingError(f"Column '{values_col}' does not exist in the expression list or the columns for table '{str(parent.this.this)}'")

                column_index = column_names.index(values_col)
                select_expr = parent_insert_expr.selects[column_index]
                right_expr.replace(select_expr.copy())

            for col in right_expr.find_all(exp.Column):
                # Transform any aliased columns into their correct expressions.
                # Examples:
                # - ON CONFLICT DO UPDATE ... EXCLUDED.col
                # - ON DUPLICATE KEY UPDATE ... new_alias.col
                table_name = (col.table or "").upper()
                if table_name == "EXCLUDED" or (values_alias_name and col.table == values_alias_name):
                    if col.name not in parent_insert_expr.named_selects:
                        # The outer INSERT did not provide a value for this column; reference the existing column
                        col.replace(exp.column(col.name))
                    else:
                        # Set it to the unaliased expression from the outer INSERT/SELECT
                        select_expr = [
                            alias_expr for alias_expr in parent_insert_expr.selects if alias_expr.alias == col.name
                        ][0]
                        new_expr = select_expr.unalias().copy()

                        if isinstance(new_expr, exp.Column) and parent_table:
                            new_expr.set("table", exp.to_identifier(parent_table.alias_or_name))

                        col.replace(new_expr)

        update_expr.set("expressions", statement.expressions)

        return update_expr

    def _convert_update_defaults_to_values(self, statement: exp.Update) -> exp.Update:
        """
        Transform the query:
            UPDATE x SET a = DEFAULT
        into:
            UPDATE x SET a = 42
        according to the table's default column values.
        """
        query = self.query
        child_table = query.get_target_as_table()
        table_query = query.object_mapping.lookup_table_query(table=child_table)
        if not table_query:
            return statement

        table_columns = table_query.get_column_defs()

        for expr in statement.expressions:
            if isinstance(expr, exp.EQ) and isinstance(expr.left, exp.Column):
                if (isinstance(expr.right, exp.Var) and expr.right.name.upper() == "DEFAULT") or (
                    isinstance(expr.right, exp.Column) and expr.right.name.upper() == "DEFAULT"
                ):
                    # Replace 'DEFAULT' with the associated column's default expression
                    self._replace_default_with_value(
                        expression=expr.right,
                        column_name=expr.left.name,
                        table_columns=table_columns,
                    )

        return statement

    def _add_information_from_merge(self, statement: exp.Insert | exp.Update) -> exp.Insert | exp.Update:
        """
        UPDATE branch of _add_information_from_merge.

        Transform a nested UPDATE (from a MERGE WHEN MATCHED branch) into a
        fully qualified UPDATE so it can be processed independently.
        """
        if not isinstance(statement, exp.Update):
            return statement

        ctx = self._extract_merge_context(statement)
        if ctx is None:
            return statement

        using = ctx["using"]
        on = ctx["on"]
        returning = ctx["returning"]
        new_ctes = [{"alias": cte.alias_or_name, "as_": cte.this} for cte in ctx["ctes"]]

        # Add the missing information to the UPDATE statement
        target = self.query.target_info.expression
        if isinstance(target, exp.Table):
            self.query.only = target.args.get("only", False)  # type: ignore

        update_expr = statement.table(self.query.target_info.expression).from_(using).where(on)
        update_expr.set("returning", returning)

        for cte in new_ctes:
            update_expr = update_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(update_expr)
        return update_expr
