from __future__ import annotations

import logging
import typing as t
from dataclasses import replace
from functools import singledispatchmethod

from sqlglot import exp
from sqlglot.optimizer import Scope

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
    SequenceNode,
)
from sqlleaf.objects.query_types import Query, ProcedureQuery

logger = logging.getLogger("sqlleaf")


class BaseGenerator:
    # A registry to store subclasses
    _dialects = {}
    dialect = ""

    @singledispatchmethod
    def process(self, cls: exp.Expression, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        raise exception.SqlLeafException(message=f"Unhandled expression type: {type(cls)}")

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

    @process.register
    def process_function(self, cls: exp.Func, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = FunctionNode(processor_ctx, ctx)
        args = util.get_function_args(expr=processor_ctx.expr)
        return node_attrs, args

    @process.register
    def process_placeholder(self, cls: exp.Placeholder, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        CREATE PROCEDURE proc(v_amount INT) AS
        SELECT v_amount     <-- placeholder
        """
        expr: exp.ColumnDef = processor_ctx.expr.this

        processor_ctx = replace(processor_ctx, new_data_type=expr.kind)
        node_attrs = VariableNode(processor_ctx, ctx)
        return node_attrs, []

    @process.register
    def process_array(self, cls: exp.Array, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in processor_ctx.expr.expressions]
        values = "{" + ",".join(values) + "}"
        node_attrs = LiteralNode(name=values, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register
    def process_window(self, cls: exp.Window, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        window_expr: exp.Window = processor_ctx.expr
        node_attrs = WindowNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register(exp.Literal)
    @process.register(exp.Boolean)
    def process_literal(self, cls: exp.Literal, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        select 'hello' as greeting
        """
        expr: exp.Literal = processor_ctx.expr
        node_attrs = LiteralNode(name=expr.sql(), processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register
    def process_star(self, cls: exp.Star, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        select count(*) as cnt
        """
        node_attrs = StarNode(processor_ctx, ctx)
        return node_attrs, []

    @process.register
    def process_null(self, cls: exp.Null, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = NullNode(processor_ctx, ctx)
        return node_attrs, []

    @process.register
    def process_neg(self, cls: exp.Neg, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT -10
        """
        expr: exp.Neg = processor_ctx.expr
        node_attrs = LiteralNode(name="-" + expr.name, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register
    def process_anonymous(self, cls: exp.Anonymous, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        User-defined functions.

        SELECT my.func()
        """
        expr: exp.Anonymous = processor_ctx.expr

        if isinstance(expr.parent, (exp.Dot,)):
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
            full_name = f"{schema}.{function}"
        else:
            # A function without a schema
            schema = ""
            function = expr.name
            full_name = function

        # Process a UDF
        node_args = list(expr.flatten())
        node_attrs = UserDefinedFunctionNode(name=function, schema=schema, processor_ctx=processor_ctx, ctx=ctx)

        table_expr = exp.table_(table=function, db=schema)
        udf_obj = processor_ctx.object_mapping.find_query(kind="udf", table=table_expr)

        if udf_obj:
            if isinstance(udf_obj.return_expr, exp.Literal):
                # TODO: this may be incorrect - analyse UDFs properly
                node_args = [udf_obj.return_expr]

        return node_attrs, node_args

    @process.register
    def process_within_group(self, cls: exp.WithinGroup, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name
        """
        expr: exp.WithinGroup = processor_ctx.expr
        processor_ctx = replace(processor_ctx, expr=expr.this)

        parent, children = self.process(expr.this, processor_ctx, ctx)
        children = list(expr.expression.find_all(exp.Column))  # expr.expression is type(exp.Order)
        return parent, children

    @process.register
    def process_select(self, cls: exp.Select, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT (SELECT 1) AS name
        """
        return None, []

    @process.register
    def process_case(self, cls: exp.Case, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT CASE WHEN count(*) > 1 THEN 1 ELSE 0 END AS my_var
        """
        # If no default is specified, the default is NULL (via ANSI SQL) TODO: however in PL/pgsql it's an error instead; check for this
        expr: exp.Case = processor_ctx.expr
        default = expr.args.get("default", exp.Null())
        thens = [if_expr.args.get("true") or if_expr.args.get("false") for if_expr in expr.args["ifs"]]
        children = [default] + thens
        return None, children

    @process.register
    def process_binary(self, cls: exp.Binary, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT 1 + 2 AS age
        """
        expr: exp.Binary = processor_ctx.expr
        if isinstance(expr, exp.Dot):
            # Process this as a UDF
            logger.debug("Found exp.Dot inside exp.Binary")
            processor_ctx = replace(processor_ctx, expr=expr.right)
            return self.process(expr.right, processor_ctx, ctx)

        node_attrs = FunctionNode(processor_ctx, ctx)
        args = [expr.left, expr.right]

        return node_attrs, args

    @process.register
    def process_var(self, cls: exp.Var, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        A variable in a stored procedure or UDF, or the keyword 'DEFAULT'
        """
        node_attrs = VarNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register
    def process_column(self, cls: exp.Column, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.Column = processor_ctx.expr

        if is_node_a_placeholder(expr=expr, query=processor_ctx.query):
            # The actual placeholder is processed elsewhere
            return None, []

        node_attrs = ColumnNode(
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
                node_attrs.rename_table(source_table, processor_ctx.query.dialect)

        if isinstance(node_attrs.source_scope, exp.Table):
            # Traverse into the table (esp. needed by "ROWS FROM")
            return node_attrs, [node_attrs.source_scope]

        return node_attrs, []

    @process.register(exp.JSONExtract)
    @process.register(exp.JSONBExtract)
    def process_json(self, cls: exp.JSONExtract, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.JSONExtract = processor_ctx.expr
        node_attrs = JsonPathNode(processor_ctx=processor_ctx, ctx=ctx)

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        return node_attrs, [source]

    @process.register
    def process_interval(self, cls: exp.Interval, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = IntervalNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    @process.register(exp.DataType)
    @process.register(exp.Identifier)
    @process.register(exp.ColumnDef)
    @process.register(exp.Table)
    def skip(self, cls, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug(f"Skipping expression: {type(processor_ctx.expr)} {str(processor_ctx.expr)}")
        return None, []

    @process.register
    def process_values(self, cls: exp.Values, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT FROM (VALUES ())
        """
        expr: exp.Values = processor_ctx.expr
        column: exp.Column = processor_ctx.child_node_attrs.expr

        # Select the correct values from the list according to the column's position in the alias
        if isinstance(expr.parent, exp.From):
            table_alias = expr.args["alias"]
            col_idx = [c.name for c in table_alias.columns].index(column.name)
            value_exprs = [tup_expr.expressions[col_idx] for tup_expr in expr.expressions]
            return None, value_exprs

        return None, []


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
