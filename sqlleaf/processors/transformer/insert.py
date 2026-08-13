import typing as t

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types

from sqlleaf.processors.transformer.base import BaseQueryTransformer
from sqlleaf.typing import E


class InsertTransformer(BaseQueryTransformer):
    """Transformer for INSERT statements."""

    def transform(self, statement: exp.Insert) -> exp.Insert:
        # Note: _convert_table_to_select, FILTER/WHERE removal, DEFAULT VALUES expansion,
        # and VALUES->SELECT conversion are all performed by preprocess() (via
        # BaseQueryTransformer.normalize_all_values) before delegating here; statement
        # is already clean of any exp.Values nodes.
        statement = self._add_information_from_merge(statement)
        statement = self._add_information_from_multitable_insert(statement)
        statement = self._process_inner_ctes(statement)

        return statement

    def postprocess(self, statement: E) -> E:
        # TODO: this is a hack to get the types annotated for UDF overloading to work for Inserts.
        #  Revisit proper type annotation so that every query (not just Inserts) has its types populated to enable UDF resolution.
        statement = annotate_types(statement, dialect=self.query.dialect, schema=self.query.object_mapping)
        return super().postprocess(statement)

    @BaseQueryTransformer._validate_syntax
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

    @BaseQueryTransformer._validate_syntax
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

    @staticmethod
    def _extract_value_lists(expression: exp.Expression) -> t.List[t.List[exp.Expression]]:
        """
        Handles exp.Tuple, exp.Select, and exp.Union.
        """
        values_lists = []
        if isinstance(expression, exp.Tuple):
            values_lists = [expression.expressions]
        elif isinstance(expression, exp.Select):
            values_lists = [[s.unalias() for s in expression.expressions]]
        return values_lists
