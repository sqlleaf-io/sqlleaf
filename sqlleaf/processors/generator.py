from __future__ import annotations
import logging
import typing as t
from dataclasses import replace

import networkx as nx
from sqlglot import exp

from sqlleaf import util

from sqlleaf.objects.query_types import Query, UpdateQuery, CopyQuery, ProcedureQuery
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import (
    EdgeAttributes,
    NodeAttributes,
    StageNode,
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
    FileNode,
)

logger = logging.getLogger("sqleaf")


class LineageGenerator:
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
            skip: self.skip,
        }

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        LineageGenerator._dialects[cls.dialect] = cls

    @classmethod
    def from_dialect(cls, class_name, *args, **kwargs):
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if target_class:
            return target_class()
        else:
            return LineageGenerator()

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

    def walk_tree_and_build_graph(
        self,
        processor_ctx: ProcessorContext,
        ctx: NodeContext,
    ) -> t.List[NodeAttributes]:
        """
        Collect the leaves of an expression so that we can get the full set of data sources and function arguments
        for a particular column.
        """
        nodes_created = []
        expr = processor_ctx.expr
        child_node_attrs = processor_ctx.child_node_attrs

        processor_func = self.get_processor(expr)
        if not processor_func:
            raise ValueError(f"Unknown expression type: {type(expr)}")

        logger.debug(f"Generating node '{expr.__class__.__name__}' with generator '{processor_func.__name__}'")
        parent_node_attrs, children = processor_func(processor_ctx=processor_ctx, ctx=ctx)

        if parent_node_attrs:
            """
            Considering Postgres inheritance operates 'behind the scenes' outside of the query's syntax), we are
            justified in implementing this behaviour in our own way: by mapping each inherited column to the query's columns.
            """
            inherited_columns_of_parent = self.find_inherited_columns_for_parent(column_node=parent_node_attrs, processor_ctx=processor_ctx, ctx=ctx)
            inherited_columns_of_child = self.find_inherited_columns_for_child(column_node=child_node_attrs, processor_ctx=processor_ctx, ctx=ctx)

            for parent_node in [parent_node_attrs] + inherited_columns_of_parent:
                for child_node in [child_node_attrs] + inherited_columns_of_child:
                    self.add_nodes_with_edge_to_graph(
                        parent_node,
                        child_node,
                        processor_ctx.graph,
                        processor_ctx.query,
                        ctx,
                    )
            nodes_created.append(parent_node_attrs)
            if parent_node_attrs.kind in ["function", "udf"]:
                ctx = replace(ctx, function_depth=ctx.function_depth + 1)
        else:
            # Re-use the parent
            parent_node_attrs = child_node_attrs

        for child_expr in children:
            child_processor_ctx = replace(processor_ctx, expr=child_expr, child_node_attrs=parent_node_attrs)
            nodes = self.walk_tree_and_build_graph(child_processor_ctx, ctx)
            nodes_created.extend(nodes)
            ctx = replace(ctx, function_arg_index=ctx.function_arg_index + 1)

        return nodes_created

    def find_inherited_columns_for_parent(self, column_node: ColumnNode, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
        """
        Find the inherited columns for a particular column, but only for the form 'SELECT FROM ONLY <table>'
        """
        inherited_columns = []
        if not isinstance(column_node, ColumnNode) or column_node.table_type == "cte":  # (processor_ctx.node and processor_ctx.node.is_parent_a_cte):
            return inherited_columns

        # Find the column's exp.Table in the expression, and check if it has 'ONLY' set
        if not column_node.expr.parent_select:
            return inherited_columns

        for table in column_node.expr.parent_select.find_all(exp.Table):
            if table.catalog == column_node.catalog and table.db == column_node.schema and table.name == column_node.table:
                parent_table = table
                if parent_table.args.get("only", False):
                    inherited_columns = []
                else:
                    inherited_columns = self.find_inherited_columns(column_node=column_node, processor_ctx=processor_ctx, ctx=ctx)
                    logger.debug(f"Including inherited columns as sources: {[c.friendly_name for c in inherited_columns]}")

        return inherited_columns

    def find_inherited_columns_for_child(self, column_node: ColumnNode, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
        """
        Find the inherited columns for a particular column, but only for the form 'MERGE|UPDATE ONLY <table>'
        """
        inherited_columns = []
        if not isinstance(column_node, ColumnNode) or column_node.table_type == "cte":
            return inherited_columns

        # Only return inherited columns for UPDATE
        if isinstance(processor_ctx.query, UpdateQuery) and not processor_ctx.query.only:
            inherited_columns = self.find_inherited_columns(column_node=column_node, processor_ctx=processor_ctx, ctx=ctx)
            logger.debug(f"Including inherited columns as targets: {[c.friendly_name for c in inherited_columns]}")

        return inherited_columns

    def find_inherited_columns(self, column_node: ColumnNode, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
        """
        Find all inherited columns from a table that are similar to some column.

        For example, if we have
            CREATE TABLE a (name VARCHAR);
            CREATE TABLE b (age VARCHAR) INHERITS (a);
        then whenever we process column `a.name`, we also need to include `b.name`.
        """
        inherited_column_nodes = []
        table = column_node.as_table()
        table_query = processor_ctx.object_mapping.find_query(kind="table", table=table)

        # Collect any columns from inherited tables with the same name
        for inh_table in table_query.inherited_by:
            col_def = [c for c in inh_table.get_column_defs() if c.name == column_node.column][0]
            col = util.column_def_to_column(column_def=col_def, parent_table=inh_table.child_table)
            col_ctx = replace(processor_ctx, expr=col)
            inh_node_attrs, _ = self.process_column(col_ctx, ctx)
            inherited_column_nodes.append(inh_node_attrs)

        return inherited_column_nodes

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

        if processor_ctx.node and expr.table in processor_ctx.node.parent_pivot_aliases:
            # On a path toward a pivot. Skip until we reach it.
            return None, []

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
        return node_attrs, []

    def process_table(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug(f"Skipping exp.Table: {str(processor_ctx.expr)}")
        return None, []

    def process_json(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.JSONExtract = processor_ctx.expr
        node_attrs = JsonPathNode(name=expr.name, processor_ctx=processor_ctx, ctx=ctx)

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
        node = processor_ctx.node

        # Select the correct values from the list according to the column's position in the alias
        if isinstance(expr.parent, exp.From):
            table_alias = expr.args["alias"]
            col_idx = [c.name for c in table_alias.columns].index(node.column.name)
            value_exprs = [tup_expr.expressions[col_idx] for tup_expr in expr.expressions]
            return None, value_exprs

        return None, []

    def skip(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        logger.debug("Skipping expression {}".format(str(processor_ctx.expr)))
        return processor_ctx.child_node_attrs, []

    def add_nodes_with_edge_to_graph(
        self,
        parent_node_attrs,
        child_node_attrs,
        graph: nx.MultiDiGraph,
        query: Query,
        ctx: NodeContext,
    ):
        """
        Add two nodes and an edge between them to the graph.
        """
        p_attrs = self.add_node_if_not_exists(parent_node_attrs, graph)
        c_attrs = self.add_node_if_not_exists(child_node_attrs, graph)

        if p_attrs and c_attrs:
            p_full_name = p_attrs.full_name
            c_full_name = c_attrs.full_name

            edge_attrs = EdgeAttributes(
                parent=p_attrs,
                child=c_attrs,
                query=query,
                select_idx=ctx.select_index,
                path_idx=-1,  # -1 is temp
            )
            graph.add_edge(p_full_name, c_full_name, attrs=edge_attrs)
            logger.debug(f"Added edge between {p_full_name} [{id(p_attrs)}] -> {c_full_name} [{id(c_attrs)}]")

    def add_node_if_not_exists(self, node_attrs: NodeAttributes, graph: nx.MultiDiGraph) -> NodeAttributes:
        """
        Add a node to the graph if it doesn't already exist.

        We need to re-use the existing node attributes so that the edge attribute objects don't refer to different-but-same-named node attributes.
        """
        if not node_attrs:
            return None

        node_name = node_attrs.full_name

        if graph.has_node(node_name):
            logger.debug(f"Re-using Node: {node_attrs.__class__}, Name: {node_attrs.full_name}")
            return graph.nodes[node_name]["attrs"]

        graph.add_node(node_name, attrs=node_attrs)
        logger.debug(f"Created Node: {node_attrs.__class__.__name__}, Name: {node_attrs.full_name}")
        return node_attrs


class PostgresLineageGenerator(LineageGenerator):
    dialect = "postgres"

    def process_table(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.Table = processor_ctx.expr
        if "rows_from" in expr.args:
            downstream_exprs = []
            for table_function in expr.args["rows_from"]:
                # Determine the immediate children of the expression.
                # These are either table functions or aliases to table functions (ColumnDefs)
                cols = list(table_function.find_all(exp.ColumnDef))
                downstream_exprs.extend(cols if cols else [table_function])

            child_column_name = processor_ctx.child_node_attrs.expr.name
            # Get the expression associated with the column name
            for i, col in enumerate(expr.alias_column_names):
                if col == child_column_name:
                    return None, [downstream_exprs[i]]

        elif expr.arg_key == "rows_from":
            # A table function inside a 'ROWS FROM'
            return None, [expr.this]

        return super().process_table(processor_ctx, ctx)

    def process_column_def(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.ColumnDef = processor_ctx.expr
        processor_ctx = replace(processor_ctx, new_data_type=expr.kind)

        if isinstance(expr.parent, exp.TableAlias):
            # An alias to a table function inside 'ROWS FROM'
            table_alias = expr.parent.alias
            if not table_alias:
                # The table alias isn't found in any attribute. Get it from the SQL string.
                # e.g. "_t0" from "_t0(x, y)"
                table_alias = expr.parent.sql().split("(")[0]

            node_attrs = ColumnNode(
                catalog="",
                schema="",
                table=table_alias,
                column=expr.name,
                processor_ctx=processor_ctx,
                ctx=ctx,
            )
            table_function: exp.Table = expr.parent.parent
            return node_attrs, [table_function]


class SnowflakeLineageGenerator(LineageGenerator):
    dialect = "snowflake"

    def process_put(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
        - Creates two nodes: FileNode and StageNode
        """
        # This steps outside the 'process_node_objects()' main method, as
        # adding logic inside the default functions is too messy.
        # We may need to return to this later.
        file_ctx = replace(processor_ctx, expr=processor_ctx.expr.args["this"])
        stage_ctx = replace(processor_ctx, expr=processor_ctx.expr.args["target"])

        file_node = FileNode(processor_ctx=file_ctx, ctx=ctx)
        stage_node = StageNode(processor_ctx=stage_ctx, ctx=ctx)

        self.add_nodes_with_edge_to_graph(file_node, stage_node, processor_ctx.graph, processor_ctx.query, ctx)

    def process_column(self, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        If the source is actually a Stage, don't try to create a Column.
        """
        query = processor_ctx.query
        if isinstance(query, CopyQuery):
            if query.is_source_a_stage:
                stage_name: exp.Var = query.source.this
                stage_ctx = replace(processor_ctx, expr=stage_name)
                parent_node_attrs = StageNode(processor_ctx=stage_ctx, ctx=ctx)
                return parent_node_attrs, []

        return super().process_column(processor_ctx, ctx)


def is_node_a_placeholder(expr: exp.Column, query: Query) -> bool:
    """
    Check if a Column is actually a Placeholder.

    For example, given
        CREATE PROCEDURE purchase(v_amount INT) AS
            SELECT v_amount as amount

    the 'v_amount' inside the SELECT will be a Column, but instead it should be a Placeholder.
    This is caused by sqlglot_lineage.lineage()
    """
    if query.parent_query and isinstance(query.parent_query, ProcedureQuery):
        args = query.parent_query.args
        arg_names = [a["name"] for a in args]
        if expr.name in arg_names:
            logger.debug(f"Skipping Column {expr.name} as it is a Placeholder")
            return True
    return False
