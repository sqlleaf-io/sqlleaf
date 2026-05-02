from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

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

    def get_expression_processors(self) -> t.Dict:
        """
        These are processed in the order they are defined.
        This is due to subclasses generally needing to be processed first.
        """
        skip = (exp.DataType, exp.Identifier)
        return {
            exp.Placeholder: self.process_placeholder,
            exp.Array: self.process_array,
            (exp.JSONExtract, exp.JSONBExtract): self.process_json,
            exp.Window: self.process_window,
            (exp.Literal, exp.Boolean): self.process_literal,
            exp.Star: self.process_star,
            exp.Cast: self.process_cast,
            exp.Null: self.process_null,
            exp.Neg: self.process_neg,
            exp.Anonymous: self.process_anonymous,
            exp.Case: self.process_case,
            exp.Var: self.process_var,
            exp.Func: self.process_function,
            exp.Binary: self.process_binary,
            # exp.Identifier: self.process_identifier,
            exp.Column: self.process_column,
            exp.Table: self.process_table,
            exp.WithinGroup: self.process_within_group,
            exp.Select: self.process_select,
            exp.Interval: self.process_interval,
            exp.ColumnDef: self.process_column_def,
            exp.Values: self.process_values,
            exp.Pivot: self.process_pivot,
            skip: self.skip,
        }

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        BaseGenerator._dialects[cls.dialect] = cls

    @classmethod
    def from_dialect(cls, class_name, *args, **kwargs):
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if not target_class:
            raise exception.SqlLeafException("Unknown dialect: '%s'" % class_name)
        return target_class()


    def get_processor(self, expr: exp.Expression):
        """
        Find the processor for the expression.
        We iterate over the list in order because earlier processors (usually subclasses)
        often take precedence.
        """
        for types, processor in self.get_expression_processors().items():
            if isinstance(expr, types):
                return processor
        return None

    def process_function(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = FunctionNode(processor_ctx, ctx)
        args = util.get_function_args(expr=processor_ctx.expr)
        return node_attrs, args

    def process_placeholder(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        CREATE PROCEDURE proc(v_amount INT) AS
        SELECT v_amount     <-- placeholder
        """
        expr: exp.ColumnDef = processor_ctx.expr.this

        processor_ctx = replace(processor_ctx, new_data_type=expr.kind)
        node_attrs = VariableNode(processor_ctx, ctx)
        return node_attrs, []

    def process_array(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in processor_ctx.expr.expressions]
        values = "{" + ",".join(values) + "}"
        node_attrs = LiteralNode(name=values, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_window(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        window_expr: exp.Window = processor_ctx.expr

        if window_expr.this.key in ["rownumber", "rank"]:
            processor_ctx = replace(processor_ctx, new_data_type=exp.DataType.build("INT"))

        node_attrs = WindowNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_literal(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        select 'hello' as greeting
        """
        expr: exp.Literal = processor_ctx.expr
        node_attrs = LiteralNode(name=expr.sql(), processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_star(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        select count(*) as cnt
        """
        node_attrs = StarNode(processor_ctx, ctx)
        return node_attrs, []

    def process_null(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = NullNode(processor_ctx, ctx)
        return node_attrs, []

    def process_cast(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT col1::timestamp AS col1_time
        """
        processor_ctx_to = replace(processor_ctx, new_data_type=processor_ctx.expr.to)
        return self.process_function(processor_ctx_to, ctx)

    def process_neg(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT -10
        """
        expr: exp.Literal = processor_ctx.expr
        node_attrs = LiteralNode(name="-" + expr.name, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_anonymous(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        expr: exp.Anonymous = processor_ctx.expr

        if isinstance(expr.parent, (exp.Dot,)):
            # Postgres UDFs don't support catalogs
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
            full_name = f"{schema}.{function}"
        else:
            # e.g. The PG sequence function nextval('serial') is anonymous
            schema = ""
            function = expr.name
            full_name = function

        # Process a sequence
        # TODO: add per-dialect processors
        if not schema and function in [
            "nextval",
            "currval",
            "setval",
        ]:  # and dialect == 'postgres'
            # 'lastval()' is not yet supported since it requires state
            seq_name_expr: exp.Literal = expr.args["expressions"][0]

            # Ensure the sequence exists
            seq_table = exp.table_(table=seq_name_expr.name, db=schema)
            if not processor_ctx.object_mapping.find_query(kind="sequence", table=seq_table):
                logger.warning(f"Sequence '{full_name}' not found.")

            node_attrs = SequenceNode(name=seq_name_expr.name, processor_ctx=processor_ctx, ctx=ctx)
            return node_attrs, []

        # Process a UDF
        node_args = list(expr.flatten())
        node_attrs = UserDefinedFunctionNode(name=function, schema=schema, processor_ctx=processor_ctx, ctx=ctx)

        table_expr = exp.table_(table=function, db=schema)
        udf_obj = processor_ctx.object_mapping.find_query(kind="udf", table=table_expr)

        # if the udf has a return_expr, insert it in here
        # if it's a literal, set the parent of 'this' as the return expr. Discard the args in lineage, but record in object
        if udf_obj:
            if isinstance(udf_obj.return_expr, exp.Literal):
                node_args = [udf_obj.return_expr]

        return node_attrs, node_args

    def process_within_group(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name
        """
        expr: exp.WithinGroup = processor_ctx.expr
        processor_ctx = replace(processor_ctx, expr=expr.this)

        parent, children = self.process_function(processor_ctx, ctx)
        children = list(expr.expression.find_all(exp.Column))  # expr.expression is type(exp.Order)
        return parent, children

    def process_select(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT (SELECT 1) AS name
        """
        return None, []

    def process_case(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT CASE WHEN count(*) > 1 THEN 1 ELSE 0 END AS my_var
        """
        # If no default is specified, the default is NULL (via ANSI SQL) TODO: however in PL/pgsql it's an error instead; check for this
        expr: exp.Case = processor_ctx.expr
        default = expr.args.get("default", exp.Null())
        thens = [if_expr.args.get("true") or if_expr.args.get("false") for if_expr in expr.args["ifs"]]
        children = [default] + thens
        return None, children

    def process_binary(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT 1 + 2 AS age
        """
        expr: exp.Binary = processor_ctx.expr
        if isinstance(expr, exp.Dot):
            # Process this as a UDF
            logger.debug("Found exp.Dot inside exp.Binary")
            processor_ctx = replace(processor_ctx, expr=expr.right)
            return self.process_anonymous(processor_ctx, ctx)

        node_attrs = FunctionNode(processor_ctx, ctx)
        args = [expr.left, expr.right]

        return node_attrs, args

    def process_var(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        A variable in a stored procedure or UDF, or the keyword 'DEFAULT'
        """
        node_attrs = VarNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_column(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.Column = processor_ctx.expr
        scope = processor_ctx.scope
        if scope:
            pivots = scope.pivots
            pivot: exp.Pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
            if pivot and pivot.alias_or_name == expr.table:
                return None, [pivot]

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

            assert isinstance(source_table, (exp.Table, exp.Values, exp.Subquery))

            if not isinstance(source_table, exp.Subquery):
                node_attrs.rename_table(source_table, processor_ctx.query.dialect)

        if isinstance(node_attrs.source_scope, exp.Table):
            # Traverse into the table (esp. needed by "ROWS FROM")
            return node_attrs, [node_attrs.source_scope]

        # TODO: PIVOT is Redshift-specific! Move to dialect

        return node_attrs, []

    def process_table(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug(f"Skipping exp.Table: {str(processor_ctx.expr)}")
        return None, []

    def process_pivot(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        SELECT * FROM (SELECT  ...) PIVOT ( ... )
        """
        # TODO: process agg funcs
        expr: exp.Pivot = processor_ctx.expr

        pivot, pivot_column_mapping = get_pivot(processor_ctx.scope)

        downstream_columns = []
        c = processor_ctx.scope.columns[ctx.select_index]

        column_name = c.name
        if any(column_name == pivot_column.name for pivot_column in pivot.args["columns"]):
            downstream_columns.extend(pivot_column_mapping[column_name])
        else:
            # The column is not in the pivot, so it must be an implicit column of the
            # pivoted source -- adapt column to be from the implicit pivoted source.
            downstream_columns.append(exp.column(c.this, table=pivot.parent.alias_or_name))

        return None, downstream_columns

    def process_json(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.JSONExtract = processor_ctx.expr
        node_attrs = JsonPathNode(processor_ctx=processor_ctx, ctx=ctx)

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        return node_attrs, [source]

    def process_interval(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = IntervalNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_column_def(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug(f"Skipping exp.ColumnDef: {str(processor_ctx.expr)}")
        return None, []

    def process_values(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
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

    def skip(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug("Skipping expression {}".format(str(processor_ctx.expr)))
        return processor_ctx.child_node_attrs, []


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


def get_pivot(scope: Scope) -> t.Tuple[exp.Pivot, dict]:
    """
    Get information related to PIVOT statements.
    """
    pivot_column_mapping = {}
    pivots = scope.pivots
    pivot: exp.Pivot = pivots[0] if len(pivots) == 1 and not pivots[0].unpivot else None
    if pivot:
        # For each aggregation function, the pivot creates a new column for each field in category
        # combined with the aggfunc. So the columns parsed have this order: cat_a_value_sum, cat_a,
        # b_value_sum, b. Because of this step wise manner the aggfunc 'sum(value) as value_sum'
        # belongs to the column indices 0, 2, and the aggfunc 'max(price)' without an alias belongs
        # to the column indices 1, 3. Here, only the columns used in the aggregations are of interest
        # in the lineage, so lookup the pivot column name by index and map that with the columns used
        # in the aggregation.
        #
        # Example: PIVOT (SUM(value) AS value_sum, MAX(price)) FOR category IN ('a' AS cat_a, 'b')
        pivot_columns = pivot.args["columns"]
        pivot_aggs_count = len(pivot.expressions)

        for i, agg in enumerate(pivot.expressions):
            agg_cols = list(agg.find_all(exp.Column))
            for col_index in range(i, len(pivot_columns), pivot_aggs_count):
                pivot_column_mapping[pivot_columns[col_index].name] = agg_cols

    return pivot, pivot_column_mapping
