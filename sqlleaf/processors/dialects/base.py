from __future__ import annotations

import logging
import typing as t
from dataclasses import replace
from functools import singledispatchmethod

from sqlglot import exp

from sqlleaf import util, exception
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    NodeAttributes,
    ColumnNode,
    IntervalNode,
    JsonPathNode,
    VarNode,
    FunctionNode,
    UserDefinedFunctionNode,
    LiteralNode,
    NullNode,
    StarNode,
    WindowNode,
    VariableNode,
)
from sqlleaf.objects.query_types import Query, ProcedureQuery

logger = logging.getLogger("sqlleaf")


class BaseGenerator:
    # A registry to store subclasses
    _dialects = {}
    dialect = ""

    @singledispatchmethod
    def process(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        raise exception.SqlLeafException(message=f"Unhandled expression type: {type(expr)}")

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        BaseGenerator._dialects[cls.dialect] = cls

    @classmethod
    def from_dialect(cls, class_name, *args, **kwargs):
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if not target_class:
            raise exception.SqlLeafException(message=f"Unknown dialect: {class_name}")
        return target_class()

    def do_grandparents(self, grandparents: t.List[exp.Expression], parent: NodeAttributes, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        Process a list of grandparents (parents of nodes in a graph).
        For example, given UPPER('A') the literal 'A' is the parent of UPPER().
        """
        if parent.kind in ["function", "udf"]:
            ctx = replace(ctx, function_depth=ctx.function_depth + 1)

        for grand_expr in grandparents:
            processor_ctx = replace(processor_ctx, expr=grand_expr, child_node_attrs=parent)
            ctx = replace(ctx, function_arg_index=ctx.function_arg_index + 1)
            yield from self.process(grand_expr, processor_ctx=processor_ctx, ctx=ctx)

    @process.register
    def process_function(self, expr: exp.Func, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        parent = FunctionNode(processor_ctx, ctx)
        yield parent, processor_ctx.child_node_attrs

        grandparents = util.get_function_args(expr=expr)
        yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)

    @process.register
    def process_placeholder(self, expr: exp.Placeholder, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        CREATE PROCEDURE proc(v_amount INT) AS
        SELECT v_amount     <-- placeholder
        """
        expr: exp.ColumnDef = expr.this
        processor_ctx = replace(processor_ctx, new_data_type=expr.kind)
        parent = VariableNode(processor_ctx, ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_array(self, expr: exp.Array, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in expr.expressions]
        values = "{" + ",".join(values) + "}"
        parent = LiteralNode(name=values, processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_window(self, expr: exp.Window, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        parent = WindowNode(processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register(exp.Literal)
    @process.register(exp.Boolean)
    def process_literal(self, expr: exp.Literal, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        select 'hello' as greeting
        """
        parent = LiteralNode(name=expr.sql(), processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_star(self, expr: exp.Star, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        select count(*) as cnt
        """
        parent = StarNode(processor_ctx, ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_null(self, expr: exp.Null, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        parent = NullNode(processor_ctx, ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_neg(self, expr: exp.Neg, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT -10
        """
        parent = LiteralNode(name="-" + expr.name, processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_anonymous(self, expr: exp.Anonymous, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        User-defined functions.

        SELECT my.func()
        """
        if isinstance(expr.parent, (exp.Dot,)):
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
        else:
            # A function without a schema
            schema = ""
            function = expr.name

        # Process a UDF
        node_args = list(expr.flatten())
        parent = UserDefinedFunctionNode(name=function, schema=schema, processor_ctx=processor_ctx, ctx=ctx)

        table_expr = exp.table_(table=function, db=schema)
        udf_obj = processor_ctx.object_mapping.find_query(kind="udf", table=table_expr)

        if udf_obj:
            if isinstance(udf_obj.return_expr, exp.Literal):
                # TODO: this may be incorrect - analyse UDFs properly
                node_args = [udf_obj.return_expr]

        yield parent, processor_ctx.child_node_attrs

        grandparents = node_args
        yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)

    @process.register
    def process_within_group(self, expr: exp.WithinGroup, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name
        """
        processor_ctx = replace(processor_ctx, expr=expr.this)
        yield from self.process(expr.this, processor_ctx, ctx)

    @process.register
    def process_select(self, expr: exp.Select, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT (SELECT 1) AS name
        """
        yield None, None

    @process.register
    def process_case(self, expr: exp.Case, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT CASE WHEN count(*) > 1 THEN 1 ELSE 0 END AS my_var
        """
        # If no default is specified, the default is NULL (via ANSI SQL) TODO: however in PL/pgsql it's an error instead; check for this
        default = expr.args.get("default", exp.Null())
        thens = [if_expr.args.get("true") or if_expr.args.get("false") for if_expr in expr.args["ifs"]]
        grandparents = [default] + thens

        parent = processor_ctx.child_node_attrs
        yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)

    @process.register
    def process_binary(self, expr: exp.Binary, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT 1 + 2 AS age
        """
        if isinstance(expr, exp.Dot):
            # Process this as a UDF
            logger.debug("Found exp.Dot inside exp.Binary")
            processor_ctx = replace(processor_ctx, expr=expr.right)
            yield from self.process(expr.right, processor_ctx, ctx)
        else:
            parent = FunctionNode(processor_ctx, ctx)
            yield parent, processor_ctx.child_node_attrs

            grandparents = [expr.left, expr.right]
            yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)

    @process.register
    def process_var(self, expr: exp.Var, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        A variable in a stored procedure or UDF, or the keyword 'DEFAULT'
        """
        parent = VarNode(processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register
    def process_column(self, expr: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        if not is_node_a_placeholder(expr=expr, query=processor_ctx.query):
            # The actual placeholder is processed elsewhere

            parent = ColumnNode(
                catalog=expr.catalog,
                schema=expr.db,
                table=expr.table,
                column=expr.name,
                processor_ctx=processor_ctx,
                ctx=ctx,
            )

            # Rename the column's table/schema/catalog to be fully qualified
            if processor_ctx.scope:
                scope = processor_ctx.scope
                source_table = dict(scope.references)[expr.table]

                if not isinstance(source_table, (exp.Table, exp.Values, exp.Subquery)):
                    raise exception.SqlLeafException(message=f"Unexpected source type: {type(source_table)}")

                if not isinstance(source_table, exp.Subquery):
                    parent.rename_table(source_table, processor_ctx.query.dialect)

            yield parent, processor_ctx.child_node_attrs

            if isinstance(parent.source_scope, exp.Table):
                # Traverse into the table (esp. needed by "ROWS FROM")
                ex = parent.source_scope
                processor_ctx = replace(processor_ctx, expr=ex, child_node_attrs=parent)
                yield from self.process(ex, processor_ctx, ctx)

    @process.register(exp.JSONExtract)
    @process.register(exp.JSONBExtract)
    def process_json(self, expr: exp.JSONExtract, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        parent = JsonPathNode(processor_ctx=processor_ctx, ctx=ctx)

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        yield parent, processor_ctx.child_node_attrs

        processor_ctx = replace(processor_ctx, expr=source, child_node_attrs=parent)
        yield from self.process(source, processor_ctx, ctx)


    @process.register
    def process_interval(self, expr: exp.Interval, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        parent = IntervalNode(processor_ctx=processor_ctx, ctx=ctx)
        yield parent, processor_ctx.child_node_attrs

    @process.register(exp.DataType)
    @process.register(exp.Identifier)
    @process.register(exp.ColumnDef)
    @process.register(exp.Table)
    def skip(self, expr: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        logger.debug(f"Skipping expression: {type(expr)} {str(expr)}")
        yield None, None

    @process.register
    def process_values(self, expr: exp.Values, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Iterator[t.Tuple[NodeAttributes, NodeAttributes]]:
        """
        SELECT FROM (VALUES ())
        """
        selected_column: exp.Column = processor_ctx.child_node_attrs.expr

        # Select the correct values from the list according to the column's position in the alias
        if isinstance(expr.parent, exp.From):
            table_alias = expr.args["alias"]
            col_idx = [c.name for c in table_alias.columns].index(selected_column.name)
            value_exprs = [tup_expr.expressions[col_idx] for tup_expr in expr.expressions]

            grandparents = value_exprs
            parent = processor_ctx.child_node_attrs
            yield from self.do_grandparents(grandparents, parent, processor_ctx, ctx)


def is_node_a_placeholder(expr: exp.Column, query: Query) -> bool:
    """
    Check if a Column is actually a Placeholder.

    For example, given
        CREATE PROCEDURE purchase(v_amount INT) AS
            SELECT v_amount as amount

    the 'v_amount' inside the SELECT will be a Column, but instead it should be a Placeholder.
    """
    if query.parent_query and isinstance(query.parent_query, ProcedureQuery):
        args = query.parent_query.args
        arg_names = [a["name"] for a in args]
        if expr.name in arg_names:
            logger.debug(f"Skipping Column {expr.name} as it is a Placeholder")
            return True
    return False
