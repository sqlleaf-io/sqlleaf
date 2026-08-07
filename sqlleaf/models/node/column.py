from __future__ import annotations

import logging
import typing as t

from sqlglot import exp
from sqlglot.optimizer import Scope
from sqlglot.optimizer.scope import ScopeType

from sqlleaf import exception
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import NodeAttributes
from sqlleaf.typing import TableOrScopeType, TableSubtype, TableType

logger = logging.getLogger("sqlleaf")


class ColumnNode(NodeAttributes):
    KIND = "column"

    def __init__(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
        source: TableOrScopeType | exp.Select | exp.Subquery | exp.Lateral | None = None,
    ):
        super().__init__(gen_ctx, pos_ctx, name=column)
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.member = ""

        self.parent_kind: str = ""
        self.parent_subkind: str = ""
        self.source_scope: TableOrScopeType | None = None

        self.set_table_properties(catalog, schema, table, gen_ctx, source=source)
        if source is not None and not isinstance(source, (exp.Subquery, Scope)):
            self._apply_rename(source, gen_ctx.query.dialect)

        # TODO: new algorithm
        # if table_type == "cte":
        #     self.member = gen_ctx.node.recursive_cte_member_kind

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "catalog": self.catalog,
            "schema": self.schema,
            "table": self.table,
        })
        return d

    def _apply_rename(self, source: exp.Table | exp.Select | exp.Lateral, dialect: str) -> None:
        """
        Change the column's source table to be its fully qualified name, not its alias,
        so that the ColumnNode is provided complete information.
        """
        column = t.cast(exp.Column, self.expr)
        _c = column.copy()

        if isinstance(source, exp.Table):
            if source.catalog:
                column.set("catalog", exp.to_identifier(source.catalog))
            if source.db:
                column.set("db", exp.to_identifier(source.db))
            if source.name:
                if dialect == "snowflake":
                    if source.this.args.get("quoted", False):  # exp.Identifier
                        column.set("table", exp.to_identifier(source.name))
                else:
                    column.set("table", exp.to_identifier(source.name))
            if _c != column:
                logger.debug(f"Renamed node {_c.sql()} to {column.sql()}")

            self.expr = column
            self.catalog = column.catalog
            self.schema = column.db
            self.table = column.table

    def set_table_properties(
        self,
        catalog: str,
        schema: str,
        table: str,
        gen_ctx: GeneratorContext,
        source: TableOrScopeType | exp.Select | exp.Subquery | exp.Lateral | None = None,
    ) -> None:
        """
        Figure out the table's kind (view, table, etc) and its subkind (temp, recursive, etc) by
        inspecting the query's scope and the mapping.
        """
        scope = gen_ctx.scope

        # logical_source is what we use to determine CTE/UDTF etc.
        logical_source = source
        if isinstance(scope, Scope):
            # Always try to get the Scope from sources if it exists for this alias
            logical_source = scope.sources.get(table) or source

            if not logical_source:
                # Nested 'rows_from' queries have their aliases in 'references'
                logical_source = dict(scope.references).get(table)

        self.source_scope = logical_source

        # If it's in references but NOT in sources, it's a derived table (e.g. ROWS FROM)
        if (
            logical_source is not None
            and isinstance(scope, Scope)
            and table not in scope.sources
            and table in dict(scope.references)
        ):
            self.parent_kind = TableType.DERIVED_TABLE
            return

        # Determine logical properties (CTE, UDTF, Derived Table)
        if self._set_kind_of_derived_table(logical_source, table, gen_ctx):
            return

        # Determine physical properties from object mapping (TABLE, VIEW, etc.)
        # Use 'source' (the exp.Expr) if available for physical name resolution
        self._set_kind_of_physical_table(catalog, schema, table, source or logical_source, gen_ctx)

    def _set_kind_of_derived_table(
        self,
        source: TableOrScopeType | exp.Select | exp.Subquery | exp.Lateral | None,
        table: str,
        gen_ctx: GeneratorContext,
    ) -> bool:
        """
        Identify if the source is a logical entity such as a CTE, UDTF, or derived table and set its properties.
        """
        if isinstance(source, Scope):
            if source.scope_type == ScopeType.CTE:
                self._set_cte_properties(source, table, gen_ctx)
                return True

            if source.scope_type == ScopeType.DERIVED_TABLE:
                self.parent_kind = TableType.DERIVED_TABLE
                return True

            if source.scope_type == ScopeType.UDTF:
                self.parent_kind = TableType.UDTF
                return True

        if isinstance(source, exp.Table) and "rows_from" in source.args:
            self.parent_kind = TableType.DERIVED_TABLE
            return True

        if isinstance(source, (exp.Select, exp.Subquery)):
            self.parent_kind = TableType.DERIVED_TABLE
            return True

        return False

    def _set_cte_properties(self, source: Scope, table: str, gen_ctx: GeneratorContext) -> None:
        """
        Resolve and set properties specific to Common Table Expressions, including recursive and materialized status.
        """
        self.parent_kind = TableType.CTE
        logger.debug("Set node to be a CTE.")

        # Check if it's recursive or materialized
        if not source.parent:
            return

        scope = gen_ctx.scope
        if not isinstance(scope, Scope):
            return

        selected_table, _ = scope.selected_sources.get(table, (None, None))
        if not selected_table:
            # Try the regular sources; may occur when column nested inside subquery references a CTE outside itself
            # In this case, skip it.
            selected_source = scope.sources.get(table)
            if selected_source and selected_source.scope_type == ScopeType.CTE:
                return
            else:
                message = f"Table '{table}' is referenced but there is no FROM containing it."
                raise exception.SqlLeafException(message=message)

        for cte in source.parent.ctes:
            if cte.alias_or_name == selected_table.name:
                if cte.args.get("materialized"):
                    self.parent_subkind = TableSubtype.MATERIALIZED
                else:
                    with_ = cte.parent
                    if isinstance(with_, exp.With) and with_.recursive:
                        logger.debug("Set node to be a recursive CTE.")
                        self.parent_subkind = TableSubtype.RECURSIVE
                break

    def _set_kind_of_physical_table(
        self,
        catalog: str,
        schema: str,
        table: str,
        source: TableOrScopeType | exp.Select | exp.Subquery | exp.Lateral | None,
        gen_ctx: GeneratorContext,
    ) -> None:
        """
        Determine the physical type of the table, such as a base table or view, by resolving its name against the object mapping.
        """
        if isinstance(source, exp.Table):
            tokens = [str(s) for s in source.parts]
        else:
            tokens = [catalog, schema, table]

        # Get the table type from the mapping
        name = ".".join([tok for tok in tokens if tok])
        if not name:
            self.parent_kind = TableType.TABLE
            return

        tab = exp.to_table(name, dialect=gen_ctx.query.dialect)
        query = gen_ctx.query.object_mapping.get_table_or_stage(table=tab, raise_on_missing=False)

        if not query or query.kind == "ctas":
            self.parent_kind = TableType.TABLE
        else:
            self.parent_kind = TableType(query.kind)

        if query and query.property:
            self.parent_subkind = TableSubtype(query.property)

    def get_column_constraint_expression(self) -> exp.ColumnConstraintKind | None:
        """
        Get the DEFAULT or GENERATED expression for this column, if it exists.
        There is only one, but this
        """
        types = (exp.DefaultColumnConstraint, exp.ComputedColumnConstraint)
        expr = t.cast(exp.ColumnDef, self.expr)
        constraints = [
            c.kind for c in expr.constraints if isinstance(c, exp.ColumnConstraint) and isinstance(c.kind, types)
        ]
        return t.cast(exp.ColumnConstraintKind, constraints[0]) if constraints else None

    @property
    def friendly_name(self) -> str:
        tokens = [self.catalog, self.schema, self.table, self.name]
        name = ".".join([tok for tok in tokens if tok])
        fields = self.friendly_fields()

        parts = []
        if name:
            parts.append(name)

        for k, v in fields.items():
            if v:
                parts.append(f"{k}={v}")

        content = " ".join(parts)
        return self.wrap(content)

    def as_table(self) -> exp.Table:
        return exp.table_(catalog=self.catalog, db=self.schema, table=self.table)

    def fields(self) -> dict[str, str]:
        f = {"kind": self.parent_kind}
        if self.parent_subkind:
            f["subkind"] = self.parent_subkind

        f |= {
            "table": self.table,
            "schema": self.schema,
            "type": self.data_type,
        }

        if self.parent_kind == TableType.CTE and self.parent_subkind == TableSubtype.RECURSIVE:
            f["member"] = self.member

        if self.parent_kind == TableType.CTE:
            f["statement"] = str(self.ctx.statement_index)

        return f


class FileColumnNode(NodeAttributes):
    KIND = "column"

    def __init__(
        self,
        column: str,
        file_format: str,
        file_path: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        super().__init__(gen_ctx, pos_ctx, name=column)
        self.file_format = file_format
        self.file_path = file_path

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "format": self.file_format,
            "path": self.file_path,
        })
        return d

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "kind": "file",
            "format": self.file_format,
            "path": self.file_path,
        }

    def friendly_fields(self) -> dict[str, str]:
        return {"path": self.file_path}


class StageColumnNode(NodeAttributes):
    KIND = "column"

    def __init__(
        self,
        column: str,
        stage: exp.Var,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
        path: str = "",
    ):
        super().__init__(gen_ctx, pos_ctx, name=column)
        self.stage = stage.name.removeprefix("@").replace('"', "")
        self.path = path

    def to_dict(self):
        d = super().to_dict()
        d.update({
            "stage": self.stage,
            "path": self.path,
        })
        return d

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "kind": "stage",
            "stage": self.stage,
            "path": self.path,
        }

    def friendly_fields(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "path": self.path,
        }
