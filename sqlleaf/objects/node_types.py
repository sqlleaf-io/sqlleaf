from __future__ import annotations
import logging
import typing as t

from sqlglot import exp
from sqlglot.optimizer.scope import ScopeType, Scope

from sqlleaf import util, exception
from sqlleaf.objects.context import NodeContext, ProcessorContext
from sqlleaf.objects.query_types import Query

logger = logging.getLogger("sqlleaf")

TableOrScopeType = exp.Table | Scope

from enum import StrEnum, auto


def _function_name(expr: exp.Expression, dialect: str) -> str:
    """
    Remove everything from the first '(' to the last ')' from a string.
    """
    try:
        # Get the name without its parameters
        name = expr.__class__().sql(dialect=dialect)
    except TypeError as e:
        name = expr.__class__().sql()

    first_bracket = name.find('(')
    if first_bracket == -1:
        return name

    last_bracket = name.rfind(')')
    if last_bracket == -1:
        return name

    return name[:first_bracket] + name[last_bracket + 1:]


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
        expr: exp.Expression,
        data_type: exp.DataType,
        ctx: NodeContext,
        column: str,
        table: str = "",
        schema: str = "",
        catalog: str = "",
        kind: str = "",
    ):
        self.expr = expr
        self.data_type = str(data_type)  # TODO: could we just assign expr.type = data_type and remove this?
        self.column = column
        self.kind = kind
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.member = ""
        self.ctx = ctx

    # Allows the class to be used a networkx node
    def __hash__(self):
        return hash(self.full_name)

    def wrap(self, name: str):
        return f"{self.kind}[{name}]"

    @property
    def full_name(self):
        return self.wrap(f"{self.column} type={self.data_type}")

    @property
    def friendly_name(self):
        return f"{self.kind}[{self.column}]"

    @property
    def id(self):
        # TODO: add correct fields
        fields = [
            self.catalog,
            self.schema,
            self.table,
            self.column,
            self.data_type,
            util.type_name(self.expr),
        ]
        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "catalog": self.catalog,
            "schema": self.schema,
            "table": self.table,
            "column": self.column,
            "data_type": self.data_type,
            "kind": self.kind,
        }


class LiteralNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="literal",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )

    @property
    def full_name(self):
        name = self.column.replace("'", '"')
        return self.wrap(
            f"{name} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = self.column.replace("'", '"')
        return f"{self.kind}[{name}]"


class ColumnNode(NodeAttributes):
    def __init__(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        processor_ctx: ProcessorContext,
        ctx: NodeContext,
        skip_table_properties: bool = False,
    ):
        expr: exp.ColumnDef = processor_ctx.expr

        super().__init__(
            kind="column",
            catalog=catalog,
            schema=schema,
            table=table,
            column=column,
            data_type=processor_ctx.data_type,
            expr=expr,
            ctx=ctx,
        )
        self.parent_kind: str = ""
        self.parent_subkind: str = ""
        self.source_scope: TableOrScopeType = None
        self.has_child_scope: bool = False    # Whether the query's source is inside an inner scope that still need to be resolved

        if not skip_table_properties:
            self.set_table_properties(catalog, schema, table, processor_ctx)

        # TODO: new algorithm
        # if table_type == "cte":
        #     self.member = processor_ctx.node.recursive_cte_member_kind


    def rename_table(self, source: exp.Table | exp.Values, dialect: str):
        """
        Change the column's source table to be its fully qualified name, not its alias,
        so that the ColumnNode is provided complete information.
        """
        column: exp.Column = self.expr
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
                logger.debug(f"Renamed node {column.sql()} to {column.sql()}")

            self.expr = column
            self.catalog = column.catalog
            self.schema = column.db
            self.table = column.table

    def set_file_properties(self, format: str, path: str):
        """
        column[name kind=file format=text type=INT path=s3://my-bucket/a/b/c]
        """
        self.parent_kind = TableType.FILE
        self.path = path
        self.format = format

    def set_table_properties(self, catalog: str, schema: str, table: str, processor_ctx: ProcessorContext):
        """
        Figure out the table's type (view/table) by inspecting the original query in the mapping.
        """
        scope = processor_ctx.scope
        if scope:
            source = scope.sources.get(table)
            if not source:
                # Nested 'rows_from' queries have their aliases in 'references'
                self.source_scope = dict(scope.references)[table]
                self.parent_kind = TableType.DERIVED_TABLE
                return

            self.source_scope: TableOrScopeType = source

            if isinstance(source, exp.Table):
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
                    for cte in source.parent.ctes:
                        if cte.alias_or_name == selected_table.name:
                            if cte.args["materialized"]:
                                self.parent_subkind = TableSubtype.MATERIALIZED
                            else:
                                with_: exp.With = cte.parent
                                if with_.recursive:
                                    # TODO: requires new algorithm
                                    logger.debug("Set node to be a recursive CTE.")
                                    self.parent_subkind = TableSubtype.RECURSIVE
                            break
                    return

                elif source.scope_type == ScopeType.DERIVED_TABLE:
                    # PIVOT
                    self.parent_kind = TableType.DERIVED_TABLE
                    return

            tokens = [str(s) for s in source.parts]
        else:
            tokens = [catalog, schema, table]

        # Get the table type from the mapping
        name = ".".join([tok for tok in tokens if tok])
        tab = exp.to_table(name, dialect=processor_ctx.query.dialect)
        query = processor_ctx.object_mapping.get_table_or_stage(table=tab, raise_on_missing=False)

        if not query or query.kind == "ctas":
            self.parent_kind = TableType.TABLE
        else:
            self.parent_kind = TableType(query.kind)
            if query.property:
                self.parent_subkind = TableSubtype(query.property)

    def get_column_constraint_expression(self) -> exp.ColumnConstraintKind:
        """
        Get the DEFAULT or GENERATED expression for this column, if it exists.
        There is only one, but this
        """
        types = (exp.DefaultColumnConstraint, exp.ComputedColumnConstraint)
        constraints = [c.kind for c in self.expr.constraints if isinstance(c.kind, types)]
        return constraints[0] if constraints else None

    def get_name(self):
        tokens = [self.catalog, self.schema, self.table, self.column]
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

        if self.parent_kind == TableType.FILE:
            parts.append(f"format={self.format} path={self.path}")

        return self.wrap(" ".join(parts))

    @property
    def friendly_name(self):
        if self.parent_kind == TableType.FILE:
            return self.wrap(f"{self.get_name()} {self.path}")
        return self.wrap(self.get_name())


class FunctionNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Binary | exp.Func = processor_ctx.expr

        if isinstance(expr, exp.Binary):
            name = expr.key
        else:
            name = _function_name(expr, processor_ctx.query.dialect)

        super().__init__(
            kind="function",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )

    @property
    def full_name(self):
        name = f"{self.column}".upper()
        return self.wrap(
            f"{name} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = f"{self.column}".upper()
        return self.wrap(name)


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        schema: str,
        processor_ctx: ProcessorContext,
        ctx: NodeContext,
    ):
        expr = processor_ctx.expr

        super().__init__(
            kind="udf",
            data_type=processor_ctx.data_type,
            expr=expr,
            schema=schema,
            column=expr.this,
            ctx=ctx,
        )

    def get_name(self):
        tokens = [self.schema, self.column]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        return self.wrap(
            f"{self.get_name()} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap(f"{self.get_name()}".upper())


class JsonPathNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.JSONExtract = processor_ctx.expr

        self.selectors = self.json_selectors(expr)
        self.selector = "".join([str(s) for s in self.selectors])
        self.selector_depth = len(self.selectors)

        super().__init__(
            kind="jsonpath",
            data_type=processor_ctx.data_type,
            expr=expr,
            column=self.selector,
            ctx=ctx,
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
        return self.wrap(f"{self.column} depth={self.selector_depth}")


class VariableNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="variable",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column='todo',
            ctx=ctx,
        )


class StarNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="star",
            data_type=exp.DataType.build("UNKNOWN"),
            expr=processor_ctx.expr,
            column="*",
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class VarNode(NodeAttributes):
    def __init__(self, processor_ctx, ctx: NodeContext):
        super().__init__(
            kind="var",
            data_type=exp.DataType.build("NULL"),
            expr=processor_ctx.expr,
            column=processor_ctx.expr.name,
            ctx=ctx,
        )


class NullNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="null",
            data_type=exp.DataType.build("NULL"),
            expr=processor_ctx.expr,
            column="null",
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(
            f"{self.column} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap("NULL")


class SequenceNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="sequence",
            data_type=exp.DataType.build("INT"),
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )


class WindowNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Window = processor_ctx.expr.this

        super().__init__(
            kind="window",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=_function_name(expr, processor_ctx.query.dialect),
            ctx=ctx,
        )


class StageNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Var = processor_ctx.expr

        if str(expr).startswith("@"):
            if not str(expr).startswith('@"'):
                # Set to uppercase only if not double-quoted
                expr.set("this", str(expr).upper())

        super().__init__(
            kind="stage",
            data_type=None,
            expr=expr,
            column=expr.name.removeprefix("@").replace('"', ""),
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class FileNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Literal = processor_ctx.expr
        filename = expr.this.removeprefix("file://")
        super().__init__(
            kind="file",
            data_type=None,
            expr=processor_ctx.expr,
            column=filename,
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class IntervalNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Interval = processor_ctx.expr
        name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        super().__init__(
            kind="interval",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(
            f"{self.column} type={self.data_type} query_depth={self.ctx.query_depth} query_width={self.ctx.query_width} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )


class PivotNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        expr: exp.Column = processor_ctx.expr
        super().__init__(
            kind="pivot",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=expr.name,
            ctx=ctx,
        )
        self.source: str = ""
        self.target: str = ""

    def set(self, source: str, target: str):
        self.source = source
        self.target = target

    @property
    def full_name(self):
        return self.wrap(f"source={self.source} target={self.target} statement={self.ctx.statement_index}")


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Query,
        select_idx: int,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query

        # These positions help unique identify syntax inside a set of SQL statements
        self.select_idx = select_idx  # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b', 'c')
        self.path_idx = path_idx  # <TODO: can I rely on the query hash instead?> The position of this edge inside a set of identical edges (e.g. two edges between nodes A->B). This can occur if the same query is used across multiple files.

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
        self.queries: t.List[Query] = []

    def add_query(self, query: Query):
        self.queries.append(query)
