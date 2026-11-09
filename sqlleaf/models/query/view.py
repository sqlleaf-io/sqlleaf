from __future__ import annotations

import typing as t

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.table import TableQuery
from sqlleaf.typing import SourceInfo, TargetInfo


class ViewQuery(Query):
    KIND = "view"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        columns: list[exp.ColumnDef],
        statement_index: int,
    ):
        source = expr.expression
        target = util.get_table(expr)

        if not target.db and object_mapping.current_user_catalog:
            # Set the schema as the currently selected one
            target.set("db", exp.to_identifier(object_mapping.current_user_catalog))

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.column_defs: list[exp.ColumnDef] = columns
        self.inherited_by: list[TableQuery] = []

        self.property: str = util.find_property(expr, self.target_info.expression, dialect)

    def is_automatically_updatable_view(self) -> bool:
        """
        A view is automatically updatable if it selects from exactly one table (or another updatable view),
        has no top-level WITH, DISTINCT, GROUP BY, HAVING, LIMIT or OFFSET clauses, and its select list
        contains no aggregates, window functions or set-returning functions.
        """
        select = self.source_info.expression
        if not isinstance(select, exp.Select):
            return False

        if any(select.args.get(arg) for arg in ("with_", "distinct", "group", "having", "limit", "offset")):
            return False

        from_ = select.args.get("from_")
        if not from_ or select.args.get("joins") or not isinstance(from_.this, exp.Table):
            return False

        if any(expr.find(exp.UDTF) for expr in select.expressions):
            return False

        base = self._get_base_query()
        if base is None:
            return False

        return not isinstance(base, ViewQuery) or base.is_automatically_updatable_view()

    def get_updatable_base_table(self) -> exp.Table:
        """
        The base table that an automatically updatable view writes to, following nested updatable views.
        """
        base = self._get_base_query()
        if isinstance(base, ViewQuery):
            return base.get_updatable_base_table()
        return base.get_target_as_table()

    def get_updatable_column_names(self) -> dict[str, str | None]:
        """
        Map each view column to the base table column it is a simple reference to, or None if it is read-only.
        """
        base = self._get_base_query()

        if isinstance(base, ViewQuery):
            base_columns = base.get_updatable_column_names()
        else:
            base_columns = {col.name: col.name for col in base.get_column_defs()}

        select = self.source_info.expression
        pairs: list[tuple[str, str | None]] = []
        for expr in select.expressions:
            column = expr.unalias()
            base_name = base_columns.get(column.name) if isinstance(column, exp.Column) else None
            pairs.append((expr.alias_or_name, base_name))

        if self.column_defs and len(self.column_defs) == len(pairs):
            return {col_def.name: base_name for col_def, (_, base_name) in zip(self.column_defs, pairs)}

        return dict(pairs)

    def _get_base_query(self) -> TableQuery | ViewQuery | None:
        from_table = self.source_info.expression.args["from_"].this
        return self.object_mapping.lookup_table_query(table=from_table, raise_on_missing=False)
