from __future__ import annotations
import logging
import typing as t

import networkx as nx
from sqlglot import exp

from sqlleaf import util
from sqlleaf.objects.context import NodeContext, ProcessorContext
from sqlleaf.objects.query_types import Query

logger = logging.getLogger("sqleaf")


def new_graph() -> nx.MultiDiGraph:
    """
    A graph has attributes along with its node and edges.
    """
    return nx.MultiDiGraph(attrs=GraphAttributes())


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
        self.table_type = ""
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
            self.table_type,
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
            "table_type": self.table_type,
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
            f"{name} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
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
        table_type = self._table_type(catalog, schema, table, processor_ctx)
        if table_type == "cte":
            self.member = processor_ctx.node.recursive_cte_member_kind

        self.table_type = table_type

    def get_column_constraint_expression(self) -> exp.ColumnConstraintKind:
        """
        Get the DEFAULT or GENERATED expression for this column, if it exists.
        There is only one, but this
        """
        types = (exp.DefaultColumnConstraint, exp.ComputedColumnConstraint)
        constraints = [c.kind for c in self.expr.constraints if isinstance(c.kind, types)]
        return constraints[0] if constraints else None

    def _table_type(self, catalog, schema, table, processor_ctx) -> str:
        """
        Figure out the table's type (view/table) by inspecting the original query in the mapping.
        """
        if processor_ctx.node:
            if processor_ctx.node.is_parent_a_cte:
                return "cte"
            if processor_ctx.node.is_parent_a_derived_table:
                return "derived_table"

        tokens = [catalog, schema, table]
        name = ".".join([tok for tok in tokens if tok])
        tab = exp.to_table(name, dialect=processor_ctx.query.dialect)
        query = processor_ctx.object_mapping.get_table_or_stage(table=tab, raise_on_missing=False)

        if not query:
            return "table"

        if query.kind == "ctas":
            return "table"
        return query.kind

    def get_name(self):
        tokens = [self.catalog, self.schema, self.table, self.column]
        return ".".join([tok for tok in tokens if tok])

    def as_table(self) -> exp.Table:
        return exp.table_(catalog=self.catalog, db=self.schema, table=self.table)

    @property
    def full_name(self):
        if "cte" in self.table_type:
            # A CTE name can be reused across statements
            if self.member:
                # Recursive CTE has the field 'member'
                return self.wrap(
                    f"{self.get_name()} type={self.data_type} subkind={self.table_type} member={self.member} statement={self.ctx.statement_index}"
                )
            return self.wrap(f"{self.get_name()} type={self.data_type} subkind={self.table_type} statement={self.ctx.statement_index}")
        else:
            return self.wrap(f"{self.get_name()} type={self.data_type} subkind={self.table_type}")

    @property
    def friendly_name(self):
        return self.wrap(self.get_name())


class FunctionNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: NodeContext):
        super().__init__(
            kind="function",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=processor_ctx.expr.key,
            ctx=ctx,
        )

    @property
    def full_name(self):
        name = f"{self.column}()".upper()
        return self.wrap(
            f"{name} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = f"{self.column}()".upper()
        return self.wrap(name)


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        name: str,
        schema: str,
        processor_ctx: ProcessorContext,
        ctx: NodeContext,
    ):
        super().__init__(
            kind="udf",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            schema=schema,
            column=name,
            ctx=ctx,
        )

    def get_name(self):
        tokens = [self.schema, self.column]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        return self.wrap(
            f"{self.get_name()} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap(f"{self.get_name()}()".upper())


class JsonPathNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: NodeContext):
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
            column=processor_ctx.node.name,
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
            f"{self.column} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
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
        super().__init__(
            kind="window",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=processor_ctx.expr.this.sql(),
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
            f"{self.column} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )


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

        self.create_edge_id()

    def create_edge_id(self):
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
        self.id = "edge:" + util.short_sha256_hash(edge_id)

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
