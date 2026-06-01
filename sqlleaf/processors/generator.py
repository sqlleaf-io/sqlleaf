from __future__ import annotations

import logging
import typing as t
from dataclasses import replace, dataclass
from enum import StrEnum, auto

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import Scope, build_scope, traverse_scope

if t.TYPE_CHECKING:
    pass

from sqlleaf import util, exception, mappings
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes, StageNode, ColumnNode, TableType, StreamNode, ProgramNode, FileColumnNode
from sqlleaf.objects.query_types import Query, UpdateQuery, CopyQuery, PutQuery, TableQuery, UnloadQuery
from sqlleaf.processors.dialects.base import BaseGenerator

logger = logging.getLogger("sqlleaf")


def generate_lineage_for_query(
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
    child_object = query.child_object
    statement = query.statement

    logger.info(f"Getting lineage for query: {statement.sql(dialect=query.dialect)}")

    pos_ctx = PositionContext(statement_index=query.get_statement_index())
    gen_ctx = GeneratorContext(
        graph=graph,
        object_mapping=object_mapping,
        query=query,
        expr=statement,
        scope=None,
    )
    generator = BaseGenerator.from_dialect(query.dialect)

    if check_for_put(generator, gen_ctx, pos_ctx):
        return graph

    if check_for_trigger(child_object, object_mapping):
        return graph

    if check_for_external_table(generator, gen_ctx, pos_ctx):
        return graph

    generate_lineage_for_columns(child_object, generator, gen_ctx, pos_ctx)
    return gen_ctx.graph


def generate_lineage_for_columns(
    table: exp.Table,
    generator: BaseGenerator,
    gen_ctx: GeneratorContext,
    pos_ctx: PositionContext,
):
    """
    Generate the lineage for a set of columns from a given table.
    """
    scope = get_scope(statement=gen_ctx.query.statement)
    scope_positions = calculate_scope_positions(scope)

    # Process the selected columns
    columns_processed = 0
    for selected_node, default_node in _iter_child_nodes(table, gen_ctx, pos_ctx):
        child_node: ColumnNode = selected_node or default_node
        logger.info(f"Calculating lineage downstream of {child_node.friendly_name}")

        # A column may have both lineage and a default expression; process both.
        # TODO: make this a CLI flag for whether to include these exprs in lineage
        if default_node:
            constraint_expr = default_node.get_column_constraint_expression()
            constraint_ctx = replace(gen_ctx, expr=constraint_expr.this, new_data_type=child_node.data_type, child_node=child_node)
            # Walk only the expression
            walk_expressions_and_build_graph(generator=generator, gen_ctx=constraint_ctx, pos_ctx=pos_ctx)

        if selected_node:
            walk_query_and_build_graph(generator, child_node, scope, scope_positions, gen_ctx, child_node.ctx)
            columns_processed += 1

    if columns_processed == 0:
        raise exception.SqlLeafException("Expected to process columns but count was 0. Review underlying logic.")


class TargetObjectType(StrEnum):
    """
    The types of objects that represent a 'target' in an SQL statement.
    """
    TABLE = auto()
    FILE = auto()
    STREAM = auto()
    PROGRAM = auto()


def _iter_child_nodes(target: exp.Table | exp.Literal | exp.Identifier, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> (
    t.Generator[t.Tuple[ColumnNode | None, ColumnNode | None]]
):
    """
    Iterate over every column of a table that was either selected in a query or has a default expression.
    """

    # Both COPY and UNLOAD can have SELECTs as their sources, which have arbitrary
    # columns that vary in length due to their sourcing from any table.
    query = gen_ctx.query
    target_type, target_columns = determine_object_type(target, gen_ctx)

    select_idx = 0

    # Iterate over every column and yield it if it is referenced in the query.
    for col_def in target_columns:
        selected_node = None
        default_node = None
        process_defaults = False
        gen_ctx = replace(gen_ctx, expr=col_def)
        pos_ctx = replace(pos_ctx, select_index=select_idx)

        match target_type:
            case TargetObjectType.FILE:
                format = util.get_file_format(target.name)
                child_node = FileColumnNode(
                    column=col_def.name,
                    format=format,
                    path=target.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case TargetObjectType.TABLE:
                child_node = ColumnNode(
                    catalog=target.catalog,
                    schema=target.db,
                    table=target.name,
                    column=col_def.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )
                process_defaults = True

            case TargetObjectType.STREAM:
                # Use the ColumnDef as the expr so that correct columns
                # are selected during walk()
                child_node = StreamNode(
                    name=target.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case TargetObjectType.PROGRAM:
                # Use the ColumnDef as the expr so that correct columns
                # are selected during walk()
                child_node = ProgramNode(
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

        if col_def.name in query.get_selected_column_names() or isinstance(query, TableQuery):
            # Check if the column is selected.
            # A 'CREATE TABLE' has no SELECT, so include all columns if this case.
            selected_node = child_node

        if process_defaults and child_node.get_column_constraint_expression():
            default_node = child_node
            # TODO: unset all index positions, set 'default=true' as position

        if selected_node or default_node:
            yield selected_node, default_node

        if selected_node:
            select_idx += 1


def determine_object_type(target, gen_ctx: GeneratorContext):
    """
    Given a target object, figure out all its columns.

    This is straightforward if source isn't a JOIN: we just use the source object's columns.
    But if it is a JOIN, we use the selected columns rather than the source's columns.
    """
    query = gen_ctx.query
    object_mapping = gen_ctx.object_mapping

    if isinstance(target, exp.Literal):
        # Use the parent table's columns as the child columns
        # Assumes this is a COPY | UNLOAD
        target_type = TargetObjectType.FILE
        columns_from_object = get_column_defs(query.source, query, object_mapping)

    elif isinstance(target, exp.Identifier):
        columns_from_object = get_column_defs(query.source, query, object_mapping)
        if target.name in ["stdin", "stdout"]:
            target_type = TargetObjectType.STREAM
        elif target.name in ["program"]:
            target_type = TargetObjectType.PROGRAM
        else:
            raise exception.SqlLeafException(f"Unknown child column name in COPY: {target.name}")

    elif isinstance(target, exp.Table):
        target_type = TargetObjectType.TABLE
        columns_from_object = get_column_defs(target, query, object_mapping)

    else:
        raise exception.SqlLeafException(f"Unknown child column type in COPY: {target}")

    return target_type, columns_from_object


def get_column_defs(target, query, object_mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
    """
    Most of the time, the sources and target are tables.
    However, with COPY/UNLOAD, they can be files or streams.

    If the target is not a table and the source is an
    """
    if isinstance(query, (CopyQuery, UnloadQuery)):
        if isinstance(query.source, exp.Select):
            columns = query.get_selected_column_names()
            return [util.str_to_column_def(col) for col in columns]

    table_query = object_mapping.get_table_or_stage(target)
    return table_query.get_column_defs()


OutputNodeType = ColumnNode | StreamNode | ProgramNode
def walk_query_and_build_graph(
    generator: BaseGenerator, child_node: OutputNodeType, scope: Scope, scope_positions, gen_ctx: GeneratorContext, pos_ctx: PositionContext
) -> None:
    """
    Walk over each query (and its subqueries) to collect the expressions for each column.
    For any expression subtrees found, invoke an 'expression walker' to process them.
    """
    gen_ctx = replace(gen_ctx, scope=scope, child_node=child_node)
    query = gen_ctx.query

    for scope_traversal in walk_query_scope(
        column=child_node.expr,
        scope=scope,
    ):
        logger.debug("----")
        if isinstance(query, CopyQuery) and query.is_target_a_stage:
            # Set the column to be a StageNode (if applicable) since we now have the lineage from using the dummy column
            gen_ctx = replace(gen_ctx, expr=query.target.this)
            child_node = StageNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx)

        logger.debug(f"Processing node expr: {scope_traversal.expression}, Id: {id(scope_traversal)}")
        logger.debug(f"Child node: {child_node.full_name}")

        height, width = scope_positions[id(scope_traversal.scope.expression)]
        child_ctx = replace(pos_ctx, query_depth=height, query_width=width)
        gen_ctx = replace(
            gen_ctx,
            expr=scope_traversal.expression,
            scope=scope_traversal.scope,
            scope_positions=scope_positions,
            child_node=child_node,
        )

        nodes = walk_expressions_and_build_graph(generator, gen_ctx, child_ctx)
        if nodes:
            logger.debug(f"Produced nodes: {[n.full_name for n in nodes]}")

            for n in nodes:
                if isinstance(n, ColumnNode) and n.has_child_scope:
                    walk_query_and_build_graph(generator, n, n.source_scope, scope_positions, gen_ctx, pos_ctx)


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
        # Create the node for this step in the lineage chain
        select = get_expression_for_column(column, scope.expression)
        st = ScopeTraversal(
            expression=select,
            scope=scope,
        )
        yield st
        logger.debug("[1] Created Node '%s', Expr: %s, Id: %s", column, select.sql(), id(st))


def walk_expressions_and_build_graph(
    generator: BaseGenerator,
    gen_ctx: GeneratorContext,
    pos_ctx: PositionContext,
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

    for edge in generator.process(gen_ctx.expr, gen_ctx, pos_ctx):
        parent_node_attrs, child_node = edge.parent, edge.child
        if parent_node_attrs:
            node_exists = gen_ctx.graph.has_node(parent_node_attrs.full_name)
            if not node_exists:
                nodes_created.append(parent_node_attrs)
            """
            Considering Postgres inheritance operates 'behind the scenes' outside of the query's syntax), we are
            justified in implementing this behaviour in our own way: by mapping each inherited column to the query's columns.
            """
            inherited_columns_of_parent = find_inherited_columns_for_parent(
                column_node=parent_node_attrs, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
            )
            inherited_columns_of_child = find_inherited_columns_for_child(
                column_node=child_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
            )

            for parent_node in [parent_node_attrs] + inherited_columns_of_parent:
                for child_node in [child_node] + inherited_columns_of_child:
                    add_nodes_with_edge_to_graph(
                        parent_node,
                        child_node,
                        gen_ctx.graph,
                        gen_ctx.query,
                        pos_ctx,
                    )
    return nodes_created


def find_inherited_columns_for_parent(
    column_node: NodeAttributes, generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext
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
                inherited_columns = find_inherited_columns(column_node=column_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
                logger.debug(f"Including inherited columns as sources: {[c.friendly_name for c in inherited_columns]}")

    return inherited_columns


def find_inherited_columns_for_child(
    column_node: NodeAttributes, generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext
) -> t.List[ColumnNode]:
    """
    Find the inherited columns for a particular column, but only for the form 'MERGE|UPDATE ONLY <table>'
    """
    inherited_columns = []
    if not isinstance(column_node, ColumnNode) or column_node.parent_kind == TableType.CTE:
        return inherited_columns

    # Only return inherited columns for UPDATE
    if isinstance(gen_ctx.query, UpdateQuery) and not gen_ctx.query.only:
        inherited_columns = find_inherited_columns(column_node=column_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        logger.debug(f"Including inherited columns as targets: {[c.friendly_name for c in inherited_columns]}")

    return inherited_columns


def find_inherited_columns(
    column_node: ColumnNode, generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext
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
    table_query = gen_ctx.object_mapping.find_query(kind="table", table=table)

    # Collect any columns from inherited tables with the same name
    for inh_table in table_query.inherited_by:
        col_def = [c for c in inh_table.get_column_defs() if c.name == column_node.name][0]
        col = util.column_def_to_column(column_def=col_def, parent_table=inh_table.child_object)
        col_ctx = replace(gen_ctx, expr=col, scope=None)  # Remove the node so that the column isn't renamed
        for edge in generator.process_column(col, col_ctx, pos_ctx):
            inh_node_attrs = edge.parent
            inherited_column_nodes.append(inh_node_attrs)

    return inherited_column_nodes


def add_nodes_with_edge_to_graph(
    parent_node_attrs: NodeAttributes,
    child_node: NodeAttributes,
    graph: nx.MultiDiGraph,
    query: Query,
    pos_ctx: PositionContext,
):
    """
    Add two nodes and an edge between them to the graph.
    """
    p_attrs = add_node_if_not_exists(parent_node_attrs, graph)
    c_attrs = add_node_if_not_exists(child_node, graph)

    if p_attrs and c_attrs:
        p_full_name = p_attrs.full_name
        c_full_name = c_attrs.full_name

        edge_attrs = EdgeAttributes(
            parent=p_attrs,
            child=c_attrs,
            query=query,
            select_idx=pos_ctx.select_index,
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
        logger.debug(f"Re-using Node: {node_attrs.__class__.__name__}, Name: {node_attrs.full_name}")
        return graph.nodes[node_name]["attrs"]

    graph.add_node(node_name, attrs=node_attrs)
    logger.debug(f"Created Node: {node_attrs.__class__.__name__}, Name: {node_attrs.full_name}")
    return node_attrs


def get_scope(statement: exp.Expr) -> Scope:
    """
    Build the scope for a statement.
    """
    statement_lineage = statement.copy()
    scope = build_scope(statement_lineage)
    if not scope:
        raise exception.SqlGlotException("Cannot build scope. Expression must be a SELECT")
    return scope


def get_expression_for_column(column: exp.Column | int, expr: exp.Expr) -> exp.Expr:
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
    expression: exp.Expr
    scope: TableOrScopeType = None


def get_column_index(column: exp.Column | int, expr: exp.Expr):
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


def is_node_inside_a_recursive_cte(expr: exp.Expr) -> bool:
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
            logger.debug("Skipping lineage for all columns of table '%s' since trigger '%s' overrides it." % (exp.table_name(child_object), t.name))
            # TODO: Use the trigger's function as the lineage
            # func = trigger.execute
            return True
    return False


def check_for_put(generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> bool:
    """
    Check if this is a PUT query.
    """
    query = gen_ctx.query
    graph = gen_ctx.graph
    expr: exp.Put = gen_ctx.expr

    if query.dialect == "snowflake" and isinstance(query, PutQuery):
        # Short-circuit this function; it's not an insert
        for edge in generator.process(expr, gen_ctx, pos_ctx):
            file_node, stage_node = edge.parent, edge.child
            add_nodes_with_edge_to_graph(file_node, stage_node, graph, query, pos_ctx)
            return True
    return False


def check_for_external_table(generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> bool:
    """
    Check if this is a CREATE EXTERNAL TABLE query.
    """
    query = gen_ctx.query

    if query.dialect == "redshift" and isinstance(query, TableQuery) and query.property == "external":
        location_expr = query.statement.args["properties"].find(exp.LocationProperty)

        for child_node, _ in _iter_child_nodes(query.child_object,gen_ctx, pos_ctx):
            gen_ctx = replace(gen_ctx, expr=location_expr, child_node=child_node)
            pos_ctx = replace(pos_ctx, select_index=child_node.ctx.select_index)
            walk_expressions_and_build_graph(generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        return True
    return False
