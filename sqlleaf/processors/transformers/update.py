"""
UpdateTransformer — handles UPDATE (and MERGE → UPDATE, ON CONFLICT) statement transformations.
"""
from sqlglot import exp

from sqlleaf.processors.transformers.base import BaseQueryTransformer


class UpdateTransformer(BaseQueryTransformer):
    """Transformer for UPDATE statements."""

    def transform(self) -> exp.Insert:
        stmt = self._convert_on_conflict_to_update(self.statement)
        if isinstance(stmt, (exp.Insert, exp.Update)):
            stmt = self._add_information_from_merge(stmt)
        if isinstance(stmt, exp.Update):
            stmt = self._convert_update_defaults_to_values(stmt)
            stmt = self._convert_update_to_insert(stmt)
        if isinstance(stmt, (exp.Insert, exp.Merge, exp.Update, exp.Delete)):
            stmt = self._process_inner_ctes(stmt)

        self.statement = stmt
        return stmt

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

        parent_insert_expr = None
        if statement.parent and isinstance(statement.parent, (exp.Insert, exp.Create)) and statement.parent.expression:
            if isinstance(statement.parent.expression, exp.Values):
                converted = self._convert_values_to_select(
                    expression=statement.parent.expression,
                    statement=statement.parent,
                )
                if isinstance(converted, (exp.Insert, exp.Create)):
                    parent_insert_expr = converted
                    statement = parent_insert_expr.args["conflict"]
            elif isinstance(statement.parent.expression, exp.Select):
                parent_insert_expr = statement.parent

        update_expr = exp.update(table=self.query.get_target_as_table())
        update_expr.set("expressions", statement.expressions)

        parent_table = None
        if statement.parent and isinstance(statement.parent, (exp.Insert, exp.Create)) and statement.parent.expression:
            parent_table = statement.parent.expression.args.get("from_", None)
            if parent_table:
                update_expr = update_expr.from_(parent_table.this)

        for eq_expr in list(update_expr.expressions):
            for col in eq_expr.right.find_all(exp.Column):
                if col.table.upper() == "EXCLUDED":
                    if parent_insert_expr is None or col.name not in parent_insert_expr.named_selects:
                        # Use the column's default (Postgres)
                        eq_expr.pop()
                    else:
                        # Set it to the unaliased expression
                        select_expr = [
                            alias_expr for alias_expr in parent_insert_expr.selects if alias_expr.alias == col.name
                        ][0]
                        new_expr = select_expr.unalias().copy()

                        if isinstance(new_expr, exp.Column) and parent_table:
                            new_expr.set("table", exp.to_identifier(parent_table.alias_or_name))

                        col.replace(new_expr)

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
        target = self.query.get_target_expression()
        if isinstance(target, exp.Table):
            self.query.only = target.args.get("only", False)  # type: ignore

        update_expr = statement.table(self.query.get_target_expression()).from_(using).where(on)
        update_expr.set("returning", returning)

        for cte in new_ctes:
            update_expr = update_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(update_expr)
        return update_expr
