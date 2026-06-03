from __future__ import annotations

import logging
import typing as t
from enum import StrEnum, auto

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, ScopeType

from sqlleaf import exception, util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.query_types import Q
from sqlleaf.typing import TableOrScopeType

logger = logging.getLogger("sqlleaf")


def _function_name(expr: exp.Expr, dialect: str) -> str:
    """
    Remove everything from the first '(' to the last ')' from a string.
    We use this method because exp.Func.sql_name() includes the function's context in its name.
    """
    try:
        # Get the name without its parameters
        name = expr.__class__().sql(dialect=dialect)
    except TypeError:
        # Some classes can't be converted to SQL using this method (e.g. CONCAT() in Postgres)
        name = expr.__class__().sql()

    first_bracket = name.find("(")
    if first_bracket == -1:
        return name

    last_bracket = name.rfind(")")
    if last_bracket == -1:
        return name

    return name[:first_bracket] + name[last_bracket + 1 :]


class TableType(StrEnum):
    TABLE = auto()
    VIEW = auto()
    CTE = auto()
    DERIVED_TABLE = auto()
    STAGE = auto()
    FILE = auto()


class TableSubtype(StrEnum):
    RECURSIVE = auto()
    TEMPORARY = auto()
    EXTERNAL = auto()
    MATERIALIZED = auto()


class NodeAttributes:
    def __init__(
        self,
        expr: exp.Expr,
        data_type: exp.DataType | None,
        pos_ctx: PositionContext,
        name: str,
        kind: str = "",
    ):
        self.expr = expr
        self.data_type = str(data_type) if data_type else ""
        self._data_type = data_type
        self.name = name
        self.kind = kind
        self.ctx = pos_ctx

    # Allows the class to be used a networkx node
    def __hash__(self):
        return hash(self.full_name)

    def get_data_type(self) -> exp.DataType:
        assert self._data_type is not None
        return self._data_type

    def wrap(self, name: str):
        return f"{self.kind}[{name}]"

    @property
    def full_name(self):
        return self.wrap(f"{self.name} type={self.data_type}")

    @property
    def friendly_name(self):
        return f"{self.kind}[{self.name}]"

    @property
    def id(self):
        # TODO: add correct fields
        fields = [
            self.name,
            self.data_type,
            util.type_name(self.expr),
        ]
        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "name": self.name,
            "data_type": self.data_type,
            "kind": self.kind,
        }


class LiteralNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="literal",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        name = self.name.replace("'", '"')
        return self.wrap(
            f"{name} type={self.data_type} "
            f"query_depth={self.ctx.query_depth} "
            f"query_width={self.ctx.query_width} "
            f"statement={self.ctx.statement_index} select={self.ctx.select_index} "
            f"func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = self.name.replace("'", '"')
        return f"{self.kind}[{name}]"


class ColumnNode(NodeAttributes):
    def __init__(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = t.cast(exp.ColumnDef, gen_ctx.expr)

        super().__init__(
            kind="column",
            name=column,
            data_type=gen_ctx.data_type,
            expr=expr,
            pos_ctx=pos_ctx,
        )
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

    @property
    def id(self):
        # TODO: add correct fields
        fields = [
            self.catalog,
            self.schema,
            self.table,
            self.name,
            self.data_type,
            util.type_name(self.expr),
        ]
        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "catalog": self.catalog,
                "schema": self.schema,
                "table": self.table,
            }
        )
        return d

    def rename_table(self, source: exp.Table | exp.Values, dialect: str):
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

    def set_table_properties(self, catalog: str, schema: str, table: str, gen_ctx: GeneratorContext):
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

        else:
            tokens = [catalog, schema, table]

        # Get the table type from the mapping
        name = ".".join([tok for tok in tokens if tok])
        tab = exp.to_table(name, dialect=gen_ctx.query.dialect)
        query = gen_ctx.object_mapping.get_table_or_stage(table=tab, raise_on_missing=False)

        if not query or query.kind == "ctas":
            self.parent_kind = TableType.TABLE
        else:
            self.parent_kind = TableType(query.kind)
            if query.property:
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

    def as_table(self) -> exp.Table:
        return exp.table_(catalog=self.catalog, db=self.schema, table=self.table)

    @property
    def full_name(self):
        parts = [
            self.get_name(),
            f"type={self.data_type}",
            f"kind={self.parent_kind}",
        ]

        if self.parent_subkind:
            parts.append(f"subkind={self.parent_subkind}")

        if self.parent_kind == TableType.CTE and self.parent_subkind == TableSubtype.RECURSIVE:
            parts.append(f"member={self.member}")

        if self.parent_kind == TableType.CTE:
            parts.append(f"statement={self.ctx.statement_index}")

        return self.wrap(" ".join(parts))

    @property
    def friendly_name(self):
        return self.wrap(self.get_name())


class FileColumnNode(NodeAttributes):
    def __init__(
        self,
        column: str,
        file_format: str,
        file_path: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = t.cast(exp.ColumnDef, gen_ctx.expr)

        super().__init__(
            kind="column",
            name=column,
            data_type=gen_ctx.data_type,
            expr=expr,
            pos_ctx=pos_ctx,
        )
        self.file_format = file_format
        self.file_path = file_path

    @property
    def id(self):
        fields = [
            self.file_path,
            self.name,
            self.data_type,
            util.type_name(self.expr),
        ]
        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "format": self.file_format,
                "path": self.file_path,
            }
        )
        return d

    @property
    def full_name(self):
        return self.wrap(f"{self.name} type={self.data_type} kind=file format={self.file_format} path={self.file_path}")

    @property
    def friendly_name(self):
        return self.wrap(f"{self.name} path={self.file_path}")


class FunctionNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(t.Union[exp.Binary, exp.Func], gen_ctx.expr)

        if isinstance(expr, exp.Binary):
            name = expr.key
        else:
            name = _function_name(expr, gen_ctx.query.dialect)

        super().__init__(
            kind="function",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        name = f"{self.name}".upper()
        return self.wrap(
            f"{name} type={self.data_type} "
            f"query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} "
            f"statement={self.ctx.statement_index} select={self.ctx.select_index} "
            f"func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = f"{self.name}".upper()
        return self.wrap(name)


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        schema: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = gen_ctx.expr

        super().__init__(
            kind="udf",
            data_type=gen_ctx.data_type,
            expr=expr,
            name=expr.this,
            pos_ctx=pos_ctx,
        )
        self.schema = schema

    def get_name(self):
        tokens = [self.schema, self.name]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        return self.wrap(
            f"{self.get_name()} type={self.data_type} "
            f"query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} "
            f"statement={self.ctx.statement_index} select={self.ctx.select_index} "
            f"func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap(f"{self.get_name()}".upper())


class JsonPathNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.JSONExtract, gen_ctx.expr)

        self.selectors = self.json_selectors(expr)
        self.selector = "".join([str(s) for s in self.selectors])
        self.selector_depth = len(self.selectors)

        super().__init__(
            kind="jsonpath",
            data_type=gen_ctx.data_type,
            expr=expr,
            name=self.selector,
            pos_ctx=pos_ctx,
        )

    def json_selectors(self, expr: exp.JSONExtract):
        """
        Collect all the JSON path elements recursively.
        e.g.
            SELECT my_json -> 'a' -> 'b'
        produces
            ['a', 'b']
        """
        elements = list(expr.expression.find_all(exp.JSONPathKey))

        left = expr.left
        while isinstance(left, (exp.JSONExtract, exp.JSONExtractScalar)):
            elements.extend(list(left.expression.find_all(exp.JSONPathKey)))
            left = left.left
        elements.reverse()

        return elements

    @property
    def full_name(self):
        return self.wrap(f"{self.name} depth={self.selector_depth}")


class VariableNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="variable",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name="todo",
            pos_ctx=pos_ctx,
        )


class StarNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="star",
            data_type=exp.DataType.build("UNKNOWN"),
            expr=gen_ctx.expr,
            name="*",
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.name}")


class VarNode(NodeAttributes):
    def __init__(self, gen_ctx, pos_ctx: PositionContext):
        super().__init__(
            kind="var",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name=gen_ctx.expr.name,
            pos_ctx=pos_ctx,
        )


class NullNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="null",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name="null",
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.wrap(
            f"{self.name} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} "
            f"statement={self.ctx.statement_index} select={self.ctx.select_index} "
            f"func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap("NULL")


class SequenceNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext, subkind: str = ""):
        super().__init__(
            kind="sequence",
            data_type=exp.DataType.build("INT"),
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )
        self.subkind = subkind

    @property
    def full_name(self):
        parts = [f"{self.name} type={self.data_type}"]
        if self.subkind:
            parts.append(f"kind={self.subkind}")
        return self.wrap(" ".join(parts))


class WindowNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Window, gen_ctx.expr.this)

        super().__init__(
            kind="window",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=_function_name(expr, gen_ctx.query.dialect),
            pos_ctx=pos_ctx,
        )


class StageNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Var, gen_ctx.expr)

        if str(expr).startswith("@"):
            if not str(expr).startswith('@"'):
                # Set to uppercase only if not double-quoted
                expr.set("this", str(expr).upper())

        super().__init__(
            kind="stage",
            data_type=None,
            expr=expr,
            name=expr.name.removeprefix("@").replace('"', ""),
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.name}")


class FileNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Literal, gen_ctx.expr)
        filename = expr.this.removeprefix("file://")
        super().__init__(
            kind="file",
            data_type=None,
            expr=gen_ctx.expr,
            name=filename,
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.name}")


class IntervalNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Interval, gen_ctx.expr)
        name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        super().__init__(
            kind="interval",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.wrap(
            f"{self.name} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} "
            f"statement={self.ctx.statement_index} select={self.ctx.select_index} "
            f"func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )


class _PivotNode(NodeAttributes):
    def __init__(self, kind: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Column, gen_ctx.expr)
        super().__init__(
            kind=kind,
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=expr.name,
            pos_ctx=pos_ctx,
        )
        self.source: str = ""
        self.target: str = ""

    def set(self, source: str, target: str):
        self.source = source
        self.target = target

    @property
    def full_name(self):
        return self.wrap(f"source={self.source} target={self.target} statement={self.ctx.statement_index}")


class PivotNode(_PivotNode):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__("pivot", gen_ctx, pos_ctx)


class UnpivotNode(_PivotNode):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__("unpivot", gen_ctx, pos_ctx)


class StreamNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="stream",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    @property
    def full_name(self):
        return self.friendly_name


class ProgramNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Copy, gen_ctx.query.statement_original)

        program = expr.args["params"][0].sql()
        name, args = (program + " ").split(" ", maxsplit=1)
        super().__init__(
            kind="program", data_type=exp.DataType.build("UNKNOWN"), expr=gen_ctx.expr, pos_ctx=pos_ctx, name=name
        )
        self.program_args = args.strip()

    @property
    def full_name(self):
        return self.wrap(f"{self.name} args='{self.program_args}'")


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Q,
        select_idx: int,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query

        # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b', 'c')
        self.select_idx = select_idx

        # The position of this edge inside a set of identical edges (e.g. two edges between nodes A->B).
        # This can occur if the same query is used across multiple files.
        # <TODO: can I rely on the query hash instead?>
        self.path_idx = path_idx

        self.path_id: str | None = None
        self.path_hop: int | None = None

    @property
    def id(self):
        # TODO: get the correct prefix from the parent queries
        prefix = "todo_sp_or_udf"
        edge_id = ":".join(
            [
                str(s)
                for s in [
                    prefix,
                    self.parent.full_name,
                    self.child.full_name,
                    self.select_idx,
                    self.path_idx,
                ]
            ]
        )
        return "edge:" + util.short_sha256_hash(edge_id)

    def to_dict(self):
        result = {
            "id": self.id,
            "parent": {
                "id": self.parent.id,
                "full_name": self.parent.full_name,
            },
            "child": {
                "id": self.child.id,
                "full_name": self.child.full_name,
            },
            "indices": {
                "select_idx": self.select_idx,
                "path_idx": self.path_idx,
            },
            "query": {"id": self.query.id},
        }
        return result


class GraphAttributes:
    def __init__(self):
        self.queries: t.List[Q] = []

    def add_query(self, query: Q):
        self.queries.append(query)


N = t.TypeVar("N", bound=NodeAttributes)
