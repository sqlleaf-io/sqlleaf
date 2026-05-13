from __future__ import annotations

import logging
import typing as t
from dataclasses import replace, dataclass

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import Scope, build_scope, find_all_in_scope, traverse_scope

if t.TYPE_CHECKING:
    pass

from sqlleaf import util, exception, mappings
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes, StageNode, ColumnNode, TableType
from sqlleaf.objects.query_types import Query, UpdateQuery, CopyQuery, PutQuery, TableQuery
from sqlleaf.processors.dialects import BaseGenerator, SnowflakeGenerator

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

    if check_for_put(generator, processor_ctx, ctx):
        return graph

    if check_for_trigger(child_table, object_mapping):
        return graph

    if check_for_external_table(generator, processor_ctx, ctx):
        return graph

    generate_column_lineage_for_columns(child_table, generator, processor_ctx, ctx)
    return graph


def generate_column_lineage_for_columns(
    table: exp.Table,
    generator: BaseGenerator,
    processor_ctx: ProcessorContext,
    ctx: NodeContext,
):
    """
    Generate the lineage for a set of columns from a given table.
    """
    scope = get_scope(statement=processor_ctx.query.statement)
    scope_positions = calculate_scope_positions(scope)

    # Process the selected columns
    for selected_node, default_node in _get_column_nodes_for_table(processor_ctx, ctx):
        child_node = selected_node or default_node
        logger.info(
            "Calculating lineage. Column: %s, Table: %s, Index: %s",
            child_node.column,
            table.name,
            child_node.ctx.select_index
        )

        # Process any default expressions for columns
        # TODO: make this a CLI flag for whether to include these exprs in lineage
        if default_node:
            constraint_expr = default_node.get_column_constraint_expression()
            constraint_ctx = replace(processor_ctx, expr=constraint_expr.this, new_data_type=child_node.data_type, child_node_attrs=child_node)
            walk_expressions_and_build_graph(generator=generator, processor_ctx=constraint_ctx, ctx=ctx)
        if selected_node:
            walk_query_and_build_graph(generator, child_node, scope, scope_positions, processor_ctx, child_node.ctx)


def _get_column_nodes_for_table(processor_ctx: ProcessorContext, ctx: NodeContext) -> (
    t.Generator[ColumnNode, ColumnNode]
):
    """
    Iterate over every column that was either selected in a query or has a default expression.
    """
    object_mapping = processor_ctx.object_mapping
    query = processor_ctx.query
    table = query.child_table

    # Ensure the child table exists with the expected columns
    child_table_query = object_mapping.get_table_or_stage(table)
    child_columns = child_table_query.get_column_defs()

    select_idx = 0

    for col_def in child_columns:
        selected_node = default_node = None
        processor_ctx = replace(processor_ctx, expr=col_def)
        ctx = replace(ctx, select_index=select_idx)

        child_node = ColumnNode(
            catalog=table.catalog,
            schema=table.db,
            table=table.name,
            column=col_def.name,
            processor_ctx=processor_ctx,
            ctx=ctx,
        )

        if isinstance(query, TableQuery) or child_node.column in query.get_selected_column_names():
            # A 'CREATE TABLE' has no SELECT, so include all columns
            selected_node = child_node

        if child_node.get_column_constraint_expression():
            default_node = child_node
            # TODO: unset all index positions, set 'default=true' as position

        if selected_node or default_node:
            yield selected_node, default_node

        if selected_node:
            select_idx += 1


def walk_query_and_build_graph(
    generator: BaseGenerator, child_node_attrs: ColumnNode, scope: Scope, scope_positions, processor_ctx: ProcessorContext, ctx: NodeContext
) -> None:
    """
    Walk over each query (and its subqueries) to collect the expressions for each column.
    For any expression subtrees found, invoke an 'expression walker' to process them.
    """
    processor_ctx = replace(processor_ctx, scope=scope, child_node_attrs=child_node_attrs)
    query = processor_ctx.query

    for scope_traversal in walk_query_scope(
        column=child_node_attrs.expr,
        scope=scope,
    ):
        logger.debug("----")
        if isinstance(query, CopyQuery) and query.is_target_a_stage:
            # Set the column to be a StageNode (if applicable) since we now have the lineage from using the dummy column
            processor_ctx = replace(processor_ctx, expr=query.target.this)
            child_node_attrs = StageNode(processor_ctx=processor_ctx, ctx=ctx)

        logger.debug(f"Processing node expr: {scope_traversal.expression}, Id: {id(scope_traversal)}")
        logger.debug(f"Child node: {child_node_attrs.full_name}")

        height, width = scope_positions[id(scope_traversal.scope.expression)]
        child_ctx = replace(ctx, query_depth=height, query_width=width)
        processor_ctx = replace(
            processor_ctx,
            expr=scope_traversal.expression,
            scope=scope_traversal.scope,
            child_node_attrs=child_node_attrs,
        )

        nodes = walk_expressions_and_build_graph(generator, processor_ctx, child_ctx)
        if nodes:
            logger.debug(f"Produced nodes: {[n.full_name for n in nodes]}")

            for n in nodes:
                if isinstance(n, ColumnNode) and n.has_child_scope:
                    walk_query_and_build_graph(generator, n, n.source_scope, scope_positions, processor_ctx, ctx)


def walk_query_scope(column: exp.Column, scope: Scope) -> t.Generator[ScopeTraversal]:
    """
    Walk over each query scope (i.e. a SELECT statement) and return the expression linked to the column.
    """
    # Subqueries, unions, etc are the first layers
    if isinstance(scope.expression, exp.Subquery):
        for source in scope.subquery_scopes:
            logger.debug("Yielding from first subquery scope")
            yield from walk_query_scope(
                column=column,
                scope=source,
            )
    elif isinstance(scope.expression, exp.SetOperation):
        # UNION, EXCEPT, etc
        index = get_column_index(column, scope.expression)

        for s in scope.union_scopes:
            logger.debug("Yielding from union scope")
            yield from walk_query_scope(
                column=index,
                scope=s,
            )
    else:
        # Create the node for this step in the lineage chain, and attach it to the previous one.
        select = get_expression_for_column(column, scope.expression)
        st = ScopeTraversal(
            expression=select,
            scope=scope,
        )
        yield st
        logger.debug("[1] Created Node '%s', Expr: %s, Id: %s", column, select.sql(), id(st))

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
    nodes_created = []

    for parent_node_attrs, child_node_attrs in generator.process(processor_ctx.expr, processor_ctx, ctx):
        if parent_node_attrs:
            node_exists = processor_ctx.graph.has_node(parent_node_attrs.full_name)
            if not node_exists:
                nodes_created.append(parent_node_attrs)
            """
            Considering Postgres inheritance operates 'behind the scenes' outside of the query's syntax), we are
            justified in implementing this behaviour in our own way: by mapping each inherited column to the query's columns.
            """
            inherited_columns_of_parent = find_inherited_columns_for_parent(
                column_node=parent_node_attrs, generator=generator, processor_ctx=processor_ctx, ctx=ctx
            )
            inherited_columns_of_child = find_inherited_columns_for_child(
                column_node=child_node_attrs, generator=generator, processor_ctx=processor_ctx, ctx=ctx
            )

            for parent_node in [parent_node_attrs] + inherited_columns_of_parent:
                for child_node in [child_node_attrs] + inherited_columns_of_child:
                    add_nodes_with_edge_to_graph(
                        parent_node,
                        child_node,
                        processor_ctx.graph,
                        processor_ctx.query,
                        ctx,
                    )
    return nodes_created


def find_inherited_columns_for_parent(
    column_node: NodeAttributes, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext
) -> t.List[ColumnNode]:
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


def find_inherited_columns_for_child(
    column_node: NodeAttributes, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext
) -> t.List[ColumnNode]:
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


def find_inherited_columns(
    column_node: ColumnNode, generator: BaseGenerator, processor_ctx: ProcessorContext, ctx: NodeContext
) -> t.List[ColumnNode]:
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
        for inh_node_attrs, _ in generator.process_column(col, col_ctx, ctx):
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
    else:
        logger.debug(f"Skipping edge creation as both nodes already exist.")


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


def get_scope(statement: exp.Expression) -> Scope:
    """
    Build the scope for a statement.
    """
    statement_lineage = statement.copy()
    scope = build_scope(statement_lineage)
    if not scope:
        raise exception.SqlGlotException("Cannot build scope. Expression must be a SELECT")
    return scope


def get_expression_for_column(column: exp.Column | int, expr: exp.Expression) -> exp.Expression:
    """
    Get the expression that matches the given column name.
    e.g. given "SELECT 1 AS a, 2 AS b", column 'b' maps to expression 2.
    """
    if isinstance(column, int):
        # The index of the query in "SELECT 1 UNION SELECT 2"
        select = expr.selects[column]
    else:
        if isinstance(expr, exp.Values):
            # SELECT FROM (VALUES ())
            selects = [expr]
        else:
            # Common path
            selects = [select for select in expr.selects if select.alias_or_name == column.name]

        if len(selects) > 1:
            message = f"Column reference '{column}' is ambiguous ({len(selects)} possible options)"
            raise exception.SqlLeafException(message)

        if selects:
            select = selects[0]
        else:
            select = expr
    return select


TableOrScopeType = exp.Table | Scope


@dataclass(frozen=True)
class ScopeTraversal:
    expression: exp.Expression
    scope: TableOrScopeType = None


def get_column_index(column: exp.Column | int, expr: exp.Expression):
    index = (
        column
        if isinstance(column, int)
        else next(
            (i for i, sel in enumerate(expr.selects) if sel.alias_or_name == column.name),
            -1,  # mypy will not allow a None here, but a negative index should never be returned
        )
    )
    if index == -1:
        raise exception.SqlLeafException(message=f"Could not find {column.name} in {expr}")
    return index


def calculate_scope_positions(scope: Scope) -> t.Dict[int, t.Dict[int, int]]:
    """
    Determine the height and width of every scope (SELECT statement) in the query's expression tree.
    This iterates over every expression in the tree via Depth-First Search, looking for scopes.
    """
    root_expr = scope.expression.root()
    scopes = {id(scope.expression): scope for scope in list(traverse_scope(root_expr))}

    # For each height, map to the current width
    heights_to_widths = {}
    expr_ids_to_positions = {}
    stack = [(root_expr, 1)]

    while stack:
        node, h = stack.pop()
        node_id = id(node)

        if node_id in scopes:
            logger.debug(f"Found scope expr ({node.__class__.__name__}): {node.sql()}")

            if not expr_ids_to_positions:   # Root node
                expr_ids_to_positions[node_id] = (0, 0)
                heights_to_widths[0] = 0
            else:
                # Track the width across varying heights
                w = heights_to_widths.get(h, 0)
                expr_ids_to_positions[node_id] = (h, w)
                heights_to_widths[h] = w + 1
                logger.debug(f"Set height={h} width={w}")
                h = h + 1
            scopes.pop(node_id)

        for v in node.iter_expressions(reverse=True):
            stack.append((v, h))

    return expr_ids_to_positions


def set_cte_properties(path: t.List[ScopeTraversal]) -> None:
    """
    Check for properties related to recursive CTEs.

    Make the first node recursive if anything in its path is also recursive.
    Otherwise, we set it to be the anchor, as its children are the anchor part
    of the expression.
    """
    root_node: ScopeTraversal = path[0]
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


def check_for_trigger(table: exp.Table, object_mapping: mappings.ObjectMapping) -> bool:
    """
    Check if a trigger overrides the query's behaviour.
    """
    if trigger := object_mapping.find_query(kind="trigger", table=table):
        if trigger.timing == "INSTEAD OF":
            logger.debug("Skipping lineage for all columns of table '%s' since trigger '%s' overrides it." % (exp.table_name(child_table), t.name))
            # TODO: Use the trigger's function as the lineage
            # func = trigger.execute
            return True
    return False


def check_for_put(generator: SnowflakeGenerator, processor_ctx: ProcessorContext, ctx: NodeContext) -> bool:
    """
    Check if this is a PUT query.
    """
    query = processor_ctx.query
    graph = processor_ctx.graph
    expr: exp.Put = processor_ctx.expr

    if query.dialect == "snowflake" and isinstance(query, PutQuery):
        # Short-circuit this function; it's not an insert
        for file_node, stage_node in generator.process(expr, processor_ctx, ctx):
            add_nodes_with_edge_to_graph(file_node, stage_node, graph, query, ctx)
            return True
    return False


def check_for_external_table(generator: SnowflakeGenerator, processor_ctx: ProcessorContext, ctx: NodeContext) -> bool:
    """
    Check if this is a CREATE EXTERNAL TABLE query.
    """
    query = processor_ctx.query

    if query.dialect == "redshift" and isinstance(query, TableQuery) and query.property == "external": #isinstance(query.statement, exp.Create):
        location_expr = query.statement.args["properties"].find(exp.LocationProperty)

        for child_node, _ in _get_column_nodes_for_table(processor_ctx, ctx):
            processor_ctx = replace(processor_ctx, expr=location_expr, child_node_attrs=child_node)
            ctx = replace(ctx, select_index=child_node.ctx.select_index)
            walk_expressions_and_build_graph(generator=generator, processor_ctx=processor_ctx, ctx=ctx)
        return True
    return False
