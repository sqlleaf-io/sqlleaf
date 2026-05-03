from __future__ import annotations

import logging
import typing as t
from dataclasses import replace, dataclass

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import build_scope, Scope, find_all_in_scope

from sqlleaf.processors.dialects import BaseGenerator

if t.TYPE_CHECKING:
    pass

from sqlleaf import util, exception, mappings
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes, StageNode, ColumnNode, TableType
from sqlleaf.objects.query_types import Query, InsertQuery, UpdateQuery, ViewQuery, CopyQuery, PutQuery, CTASQuery, ProcedureQuery

logger = logging.getLogger("sqlleaf")


def generate_column_lineage_for_query(
    query: Query,
    graph: nx.MultiDiGraph,
    object_mapping: mappings.ObjectMapping,
) -> nx.MultiDiGraph:
    """
    Calculate the lineage for an SQL query.

    We collect all the columns from the query's target table, and then iterate
    over sqlglot's abstract syntax tree (AST) to determine the set of nodes
    and transformations used along the path to reach the table's columns.
    """
    child_table = query.child_table
    statement = query.statement

    logger.info(f"Getting lineage for query: {statement.sql(dialect=query.dialect)}")

    ctx = NodeContext(statement_index=query.get_statement_index())
    processor_ctx = ProcessorContext(
        graph=graph,
        object_mapping=object_mapping,
        query=query,
        expr=statement,
        scope=None,
    )

    generator = BaseGenerator.from_dialect(query.dialect)
    if isinstance(query, PutQuery):
        # Short-circuit this function; it's not an insert
        file_node, [stage_node] = generator.process_put(None, processor_ctx, ctx)
        add_nodes_with_edge_to_graph(file_node, stage_node, graph, query, ctx)
        return graph

    # Check if a trigger overrides the query's behaviour
    if trigger := object_mapping.find_query(kind="trigger", table=child_table):
        if trigger.timing == "INSTEAD OF":
            logger.debug("Skipping lineage for all columns of table '%s' since trigger '%s' overrides it." % (exp.table_name(child_table), t.name))
            # TODO: Use the trigger's function as the lineage
            # func = trigger.execute

            return graph

    statement_lineage = statement.copy()
    scope = build_scope(statement_lineage)
    if not scope:
        raise exception.SqlGlotException("Cannot build scope. Expression must be a SELECT")

    # Ensure the child table exists with the expected columns
    child_table_query = object_mapping.get_table_or_stage(query.child_table)
    child_columns = child_table_query.get_column_defs()
    selected_column_names = query.get_selected_column_names()

    select_idx = 0
    for col_def in child_columns:
        ctx = NodeContext(select_index=select_idx, statement_index=query.get_statement_index())
        processor_ctx = ProcessorContext(
            graph=graph,
            object_mapping=object_mapping,
            query=query,
            expr=col_def,
            scope=None,
        )
        col_name = col_def.name

        child_node = ColumnNode(
            catalog=child_table.catalog,
            schema=child_table.db,
            table=child_table.name,
            column=col_name,
            processor_ctx=processor_ctx,
            ctx=ctx,
        )

        if constraint_expr := child_node.get_column_constraint_expression():
            # Process the column's default expression
            # TODO: make this a CLI flag for whether to include these exprs in lineage
            constraint_ctx = replace(processor_ctx, expr=constraint_expr.this, new_data_type=col_def.kind, child_node_attrs=child_node)
            walk_expressions_and_build_graph(generator=generator, processor_ctx=constraint_ctx, ctx=ctx)

        if col_name not in selected_column_names:
            continue

        logger.info(
            "Calculating lineage. Column: %s, Table: %s, Index: %s",
            col_name,
            child_table.name,
            select_idx,
        )

        """
        Collect the functions for each Node, and then extract the Node's Expression into a common object type
        that contains only the essential information we need.
        """
        walk_query_and_build_graph(generator, child_node, scope, processor_ctx, ctx, node_depth=0)
        select_idx += 1

    return graph


def walk_query_and_build_graph(generator: BaseGenerator, child_node_attrs: ColumnNode, scope: Scope, processor_ctx: ProcessorContext, ctx: NodeContext, node_depth: int):
    """
    Walk over each query (and its subqueries) to collect the expressions for each column.
    """
    processor_ctx = replace(processor_ctx, scope=scope, child_node_attrs=child_node_attrs)
    query = processor_ctx.query

    for node in walk_query_scope(
        column=child_node_attrs.expr,
        scope=scope,
    ):
        logger.debug("----")
        # Node depth distinguishes identical query elements across CTEs

        if isinstance(query, CopyQuery) and query.is_target_a_stage:
            # Set the column to be a StageNode (if applicable) since we now have the lineage from using the dummy column
            processor_ctx = replace(processor_ctx, expr=query.target.this)
            child_node_attrs = StageNode(processor_ctx=processor_ctx, ctx=ctx)

        logger.debug(f"Processing node expr: {node.expression}, Id: {id(node)}")
        logger.debug(f"Child node: {child_node_attrs.full_name}")

        total_depth = node_depth + node.current_depth
        child_ctx = replace(ctx, node_depth=total_depth)
        processor_ctx = replace(
            processor_ctx,
            expr=node.expression,
            scope=node.scope,
            child_node_attrs=child_node_attrs,
        )

        nodes = walk_expressions_and_build_graph(generator, processor_ctx, child_ctx)
        if nodes:
            logger.debug(f"Produced nodes: {[n.full_name for n in nodes]}")

            for n in nodes:
                if isinstance(n, ColumnNode) and n.has_child_scope:
                    walk_query_and_build_graph(generator, n, n.source_scope, processor_ctx, ctx, node_depth=total_depth + 1)


def walk_query_scope(column: exp.Column, scope: Scope, current_depth: int = 0):
    if isinstance(scope.expression, exp.Subquery):
        for source in scope.subquery_scopes:
            logger.debug("Yielding from first subquery scope")
            yield from walk_query_scope(
                column=column,
                scope=source,
                current_depth=current_depth + 1,
            )
    elif isinstance(scope.expression, exp.SetOperation):
        # UNION, EXCEPT, etc
        index = get_column_index(column, scope)

        for s in scope.union_scopes:
            logger.debug("Yielding from union scope")
            yield from walk_query_scope(
                column=index,
                scope=s,
                current_depth=current_depth + 1,
            )
    else:
        # Create the node for this step in the lineage chain, and attach it to the previous one.
        select = get_select(column, scope)
        node = Node(
            expression=select,
            scope=scope,
            current_depth=current_depth,
        )
        yield node
        logger.debug("[1] Created Node '%s', Expr: %s, Id: %s", column, select.sql(), id(node))

        subquery_scopes = {id(subquery_scope.expression): subquery_scope for subquery_scope in scope.subquery_scopes}

        for subquery in find_all_in_scope(select, exp.UNWRAPPED_QUERIES):
            # e.g. SELECT ARRAY(SELECT 1), UPDATE x SET y = (SELECT 1)
            subquery_scope = subquery_scopes.get(id(subquery))
            if not subquery_scope:
                logger.warning("Unknown subquery scope: %s", subquery.sql())
                continue

            for name in subquery.named_selects:
                logger.debug("Yielding from second subquery scope")
                yield from walk_query_scope(
                    column=exp.column(name),
                    scope=subquery_scope,
                    current_depth=current_depth + 1,
                )


def walk_expressions_and_build_graph(
    generator: BaseGenerator,
    processor_ctx: ProcessorContext,
    ctx: NodeContext,
) -> t.List[NodeAttributes]:
    """
    Collect the leaves of an expression so that we can get the full set of data sources and function arguments
    for a particular column.

    For example, given the query:
        INSERT INTO x (name)
        SELECT UPPER(CONCAT('p', 'q')) AS name
    We construct the graph by moving 'upwards' from the target (child) to source (parent):
    - Start with child 'x.name'. Its parent is 'UPPER', so we create a FunctionNode.
    - Next, the parent of UPPER is CONCAT, which is also x.name's grandparent. This too becomes a FunctionNode.
    - Finally, the parents of CONCAT are 'p' and 'q'. These become LiteralNodes.
    """
    expr = processor_ctx.expr

    nodes_created = []
    child_node_attrs = processor_ctx.child_node_attrs
    # TODO: upgrade Python to easily access the called function
    # logger.debug(f"Generating node '{expr.__class__.__name__}' with generator '{processor_func.__name__}'")
    parent_node_attrs, grandparent_exprs = generator.process(expr, processor_ctx, ctx)

    if parent_node_attrs:
        node_exists = processor_ctx.graph.has_node(parent_node_attrs.full_name)
        """
        Considering Postgres inheritance operates 'behind the scenes' outside of the query's syntax), we are
        justified in implementing this behaviour in our own way: by mapping each inherited column to the query's columns.
        """
        inherited_columns_of_parent = find_inherited_columns_for_parent(column_node=parent_node_attrs, generator=generator, processor_ctx=processor_ctx, ctx=ctx)
        inherited_columns_of_child = find_inherited_columns_for_child(column_node=child_node_attrs, generator=generator, processor_ctx=processor_ctx, ctx=ctx)

        for parent_node in [parent_node_attrs] + inherited_columns_of_parent:
            for child_node in [child_node_attrs] + inherited_columns_of_child:
                add_nodes_with_edge_to_graph(
                    parent_node,
                    child_node,
                    processor_ctx.graph,
                    processor_ctx.query,
                    ctx,
                )
        if not node_exists:
            nodes_created.append(parent_node_attrs)
        if parent_node_attrs.kind in ["function", "udf"]:
            ctx = replace(ctx, function_depth=ctx.function_depth + 1)
    else:
        # Re-use the parent
        parent_node_attrs = child_node_attrs

    # Recursively process any grandparent expressions
    for grandparent_expr in grandparent_exprs:
        grandparent_processor_ctx = replace(processor_ctx, expr=grandparent_expr, child_node_attrs=parent_node_attrs)
        nodes = walk_expressions_and_build_graph(generator, grandparent_processor_ctx, ctx)
        nodes_created.extend(nodes)
        ctx = replace(ctx, function_arg_index=ctx.function_arg_index + 1)

    return nodes_created


def find_inherited_columns_for_parent(column_node: ColumnNode, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
    """
    Find the inherited columns for a particular column, but only for the form 'SELECT FROM ONLY <table>'
    TODO fix comments etc
    """
    if not isinstance(column_node, ColumnNode) or column_node.parent_kind == TableType.CTE:
        return []

    # Find the column's exp.Table in the expression, and check if it has 'ONLY' set
    if not column_node.expr.parent_select:
        return []

    inherited_columns = []
    for table in column_node.expr.parent_select.find_all(exp.Table):
        if table.catalog == column_node.catalog and table.db == column_node.schema and table.name == column_node.table:
            parent_table = table
            if parent_table.args.get("only", False):
                inherited_columns = []
            else:
                inherited_columns = find_inherited_columns(column_node=column_node, generator=generator, processor_ctx=processor_ctx, ctx=ctx)
                logger.debug(f"Including inherited columns as sources: {[c.friendly_name for c in inherited_columns]}")

    return inherited_columns


def find_inherited_columns_for_child(column_node: ColumnNode, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
    """
    Find the inherited columns for a particular column, but only for the form 'MERGE|UPDATE ONLY <table>'
    """
    inherited_columns = []
    if not isinstance(column_node, ColumnNode) or column_node.parent_kind == TableType.CTE:
        return inherited_columns

    # Only return inherited columns for UPDATE
    if isinstance(processor_ctx.query, UpdateQuery) and not processor_ctx.query.only:
        inherited_columns = find_inherited_columns(column_node=column_node, generator=generator, processor_ctx=processor_ctx, ctx=ctx)
        logger.debug(f"Including inherited columns as targets: {[c.friendly_name for c in inherited_columns]}")

    return inherited_columns


def find_inherited_columns(column_node: ColumnNode, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext) -> t.List[ColumnNode]:
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
        col_ctx = replace(processor_ctx, expr=col, scope=None)  # Remove the node so that the column isn't renamed
        inh_node_attrs, _ = generator.process_column(None, col_ctx, ctx)
        inherited_column_nodes.append(inh_node_attrs)

    return inherited_column_nodes


def add_nodes_with_edge_to_graph(
    parent_node_attrs: NodeAttributes,
    child_node_attrs: NodeAttributes,
    graph: nx.MultiDiGraph,
    query: Query,
    ctx: NodeContext,
):
    """
    Add two nodes and an edge between them to the graph.
    """
    p_attrs = add_node_if_not_exists(parent_node_attrs, graph)
    c_attrs = add_node_if_not_exists(child_node_attrs, graph)

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


def add_node_if_not_exists(node_attrs: NodeAttributes, graph: nx.MultiDiGraph) -> NodeAttributes:
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


def get_select(column: exp.Column | int, scope: Scope):
    if isinstance(column, int):
        # The index of the query in "SELECT 1 UNION SELECT 2"
        select = scope.expression.selects[column]
    else:
        if isinstance(scope.expression, exp.Values):
            # SELECT FROM (VALUES ())
            selects = [scope.expression]
        else:
            selects = [select for select in scope.expression.selects if select.alias_or_name == column.name]
        if len(selects) > 1:
            message = f"Column reference '{column}' is ambiguous ({len(selects)} possible options)"
            raise exception.SqlLeafException(message)
        if selects:
            select = selects[0]
        else:
            select = scope.expression
    return select


TableOrScopeType = exp.Table | Scope

@dataclass(frozen=True)
class Node:
    expression: exp.Expression
    current_depth: int
    scope: TableOrScopeType = None

def get_column_index(column: exp.Column | int, scope: Scope):
    index = (
        column
        if isinstance(column, int)
        else next(
            (i for i, sel in enumerate(scope.expression.selects) if sel.alias_or_name == column.name),
            -1,  # mypy will not allow a None here, but a negative index should never be returned
        )
    )
    if index == -1:
        raise ValueError(f"Could not find {column.name} in {scope.expression}")
    return index


def set_cte_properties(path: t.List[Node]) -> None:
    """
    Check for properties related to recursive CTEs.

    Make the first node recursive if anything in its path is also recursive.
    Otherwise, we set it to be the anchor, as its children are the anchor part
    of the expression.
    """
    root_node: Node = path[0]
    if root_node.is_parent_a_recursive_cte:
        for n in path[1:]:
            if is_node_inside_a_recursive_cte(n):
                if n.is_parent_a_recursive_cte:
                    root_node.recursive_cte_member_kind = "recursive"
                    n.recursive_cte_member_kind = "anchor"
                else:
                    root_node.recursive_cte_member_kind = "anchor"
            break


def is_node_inside_a_recursive_cte(expr: exp.Expression) -> bool:
    """
    Check if we're inside a recursive CTE
    """
    if parent_cte := expr.find_ancestor(exp.CTE):
        if parent_cte.parent.recursive:
            return True
    return False
