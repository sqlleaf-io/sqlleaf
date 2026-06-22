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
    ):
        super().__init__(gen_ctx, pos_ctx, name=column)
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.member = ""

        self.parent_kind: str = ""
        self.parent_subkind: str = ""
        self.source_scope: TableOrScopeType | None = None
        self.has_child_scope: bool = (
            False  # Whether the query's source is inside an inner scope that still need to be resolved
        )

        self.set_table_properties(catalog, schema, table, gen_ctx)

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

    def rename_table(self, source: exp.Table | exp.Values, dialect: str) -> None:
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

    def set_table_properties(self, catalog: str, schema: str, table: str, gen_ctx: GeneratorContext) -> None:
        """
        Figure out the table's type (view/table) by inspecting the original query in the mapping.
        """
        tokens = []
        scope = gen_ctx.scope
        if isinstance(scope, Scope):
            source = scope.sources.get(table)
            if not source:
                # Nested 'rows_from' queries have their aliases in 'references'
                self.source_scope = dict(scope.references).get(table)  # tyy: ignore[invalid-assignment]
                self.parent_kind = TableType.DERIVED_TABLE
                return

            self.source_scope: TableOrScopeType = source

            if isinstance(source, exp.Table):
                tokens = [str(s) for s in source.parts]
                if "rows_from" in source.args:
                    self.parent_kind = TableType.DERIVED_TABLE
                    return

            elif isinstance(source, Scope):
                self.has_child_scope = True

                if isinstance(source.expression, exp.Values):
                    self.parent_kind = TableType.DERIVED_TABLE
                    return
                elif source.scope_type == ScopeType.CTE:
                    selected_table, _ = scope.selected_sources.get(table, (None, None))
                    if not selected_table:
                        message = f"Table '{table}' is referenced but there is no FROM containing it."
                        raise exception.SqlLeafException(message=message)

                    logger.debug("Set node to be a CTE.")
                    self.parent_kind = TableType.CTE

                    # Check if the CTE is a subtype
                    if source.parent:
                        for cte in source.parent.ctes:
                            if cte.alias_or_name == selected_table.name:
                                if cte.args["materialized"]:
                                    self.parent_subkind = TableSubtype.MATERIALIZED
                                else:
                                    with_ = cte.parent
                                    if isinstance(with_, exp.With) and with_.recursive:
                                        # TODO: requires new algorithm
                                        logger.debug("Set node to be a recursive CTE.")
                                        self.parent_subkind = TableSubtype.RECURSIVE
                                break
                    return

                elif source.scope_type == ScopeType.DERIVED_TABLE:
                    # PIVOT
                    self.parent_kind = TableType.DERIVED_TABLE
                    return

                elif source.scope_type == ScopeType.UDTF:
                    self.parent_kind = TableType.UDTF
                    return

        else:
            tokens = [catalog, schema, table]

        # Get the table type from the mapping
        name = ".".join([tok for tok in tokens if tok])
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

    def get_name(self):
        tokens = [self.catalog, self.schema, self.table, self.name]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        fields_dict = self.fields()
        fields = " ".join([f"{k}={v}" for k, v in fields_dict.items() if v])
        return self.wrap(fields, with_positions=self.with_positions)

    def as_table(self) -> exp.Table:
        return exp.table_(catalog=self.catalog, db=self.schema, table=self.table)

    def fields(self) -> dict[str, str]:
        f = {
            "name": self.name,
            "table": self.table,
            "schema": self.schema,
            "type": self.data_type,
            "kind": self.parent_kind,
        }

        if self.parent_subkind:
            f["subkind"] = self.parent_subkind

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
