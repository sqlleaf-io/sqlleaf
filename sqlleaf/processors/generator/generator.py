from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass, replace

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import Scope, build_scope

if t.TYPE_CHECKING:
    pass

from sqlleaf import exception, mappings, util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    ColumnNode,
    EdgeAttributes,
    N,
    TargetNodeType,
)
from sqlleaf.models.query import (
    PutQuery,
    Q,
    QueryHolder,
    TableQuery,
    UpdateQuery,
)
from sqlleaf.processors.generator.dialects.base import BaseGenerator
from sqlleaf.typing import E, TableOrScopeType, TableType

logger = logging.getLogger("sqlleaf")


def generate_lineage_for_query(
    holder: QueryHolder,
    graph: nx.MultiDiGraph,
) -> nx.MultiDiGraph:
    """
    Calculate the lineage for an SQL query.

    We collect all the columns from the query's target table, and then iterate
    over sqlglot's abstract syntax tree (AST) to determine the set of nodes
    and transformations used along the path to reach the table's columns.

    Everything is extracted: columns, literals, functions, etc.
    """
    query = holder.transformed

    logger.debug("---- Generator ----")
    logger.debug(f"Generating for: {type(query)}")
    statement = query.statement
    logger.debug(f"Getting lineage for query: {statement.sql(dialect=query.dialect)}")
    logger.debug(repr(statement))

    target_object = query.target_info.expression
    pos_ctx = PositionContext(statement_index=query.get_statement_index())
    gen_ctx = GeneratorContext(
        graph=graph,
        query=query,
        expr=statement,
        child_node=target_object,
        scope=None,
    )
    generator = BaseGenerator.from_dialect(query.dialect)

    if check_for_put(generator, gen_ctx, pos_ctx):
        return graph

    if check_for_trigger(target_object, query.object_mapping):
        return graph

    if check_for_external_table(generator, gen_ctx, pos_ctx):
        return graph

    generate_lineage_for_columns(generator, gen_ctx, pos_ctx)

    return graph


def generate_lineage_for_columns(
    generator: BaseGenerator,
    gen_ctx: GeneratorContext,
    pos_ctx: PositionContext,
):
    """
    Generate the lineage for a set of columns from a given table.
    """
    scope = get_scope(statement=gen_ctx.expr)
    gen_ctx.scope_positions.calculate(scope)

    # Process the selected columns
    for selected_node, default_node in generator.iter_child_nodes(gen_ctx, pos_ctx):
        child_node: TargetNodeType | None = selected_node or default_node
        if not child_node:
            break

        logger.info(f"Calculating lineage downstream of {child_node.friendly_name}")

        # A column may have both lineage and a default expression; process both.
        # TODO: make this a CLI flag for whether to include these exprs in lineage
        if default_node:
            constraint_expr = default_node.get_column_constraint_expression()
            if constraint_expr and constraint_expr.this:
                constraint_ctx = replace(
                    gen_ctx,
                    expr=constraint_expr.this,
                    new_data_type=child_node.data_type,
                    child_node=child_node,
                )
                # Walk only the expression
                walk_expressions_and_build_graph(generator=generator, gen_ctx=constraint_ctx, pos_ctx=pos_ctx)

        if selected_node:
            walk_query_and_build_graph(generator, child_node, scope, gen_ctx, child_node.ctx)


def walk_query_and_build_graph(
    generator: BaseGenerator,
    child_node: TargetNodeType,
    scope: Scope,
    gen_ctx: GeneratorContext,
    pos_ctx: PositionContext,
) -> None:
    """
    Walk over each query (and its subqueries) to collect the expressions for each column.
    For any expression subtrees found, invoke an 'expression walker' to process them.
    """
    gen_ctx = gen_ctx.new(scope=scope, child_node=child_node)

    for scope_traversal in walk_query_scope(
        column=t.cast(t.Union[exp.Column, int], child_node.expr),
        scope=scope,
    ):
        logger.debug(f"Processing node expr: {scope_traversal.expression}, Id: {id(scope_traversal)}")
        logger.debug(f"Child node: {child_node.full_name}")

        height, width = gen_ctx.scope_positions.get_scope_for_expr(scope_traversal.scope.expression)
        child_ctx = pos_ctx.new(query_depth=height, query_width=width)
        gen_ctx = replace(
            gen_ctx,
            expr=scope_traversal.expression,
            scope=scope_traversal.scope,
            child_node=child_node,
        )

        nodes = walk_expressions_and_build_graph(generator, gen_ctx, child_ctx)
        if nodes:
            logger.debug(f"Produced nodes: {[n.full_name for n in nodes]}")

            for n in nodes:
                if isinstance(n, ColumnNode) and isinstance(n.source_scope, Scope):
                    # There are additional expressions to traverse (e.g. inside a CTE)
                    walk_query_and_build_graph(generator, n, n.source_scope, gen_ctx, pos_ctx)


def walk_query_scope(column: exp.Column | int, scope: Scope) -> t.Generator[ScopeTraversal]:
    """
    Walk over each query scope (i.e. nested or standalone SELECT statement) and return the expression linked to the column.
    """
    # Subqueries, unions, etc are the first layers
    if isinstance(scope.expression, exp.Subquery):
        sources = scope.subquery_scopes
        for source in sources:
            logger.debug("Yielding from first subquery scope")
            yield from walk_query_scope(
                column=column,
                scope=source,
            )
        if sources:
            return
    elif isinstance(scope.expression, exp.SetOperation):
        # UNION, EXCEPT, etc
        index = get_column_index(column, scope.expression)

        sources = scope.union_scopes
        for source in sources:
            logger.debug("Yielding from union scope")
            yield from walk_query_scope(
                column=index,
                scope=source,
            )
        if sources:
            return
    elif isinstance(scope.expression, exp.Lateral):
        # LATERAL ( SELECT )
        sources = [src for src in scope.sources.values() if isinstance(src, Scope)]
        for source in sources:
            if isinstance(source, Scope):
                logger.debug("Yielding from lateral scope")
                yield from walk_query_scope(
                    column=column,
                    scope=source,
                )
        if sources:
            return

    # Get the associated expression for the column name
    select = get_expression_for_column(column, scope.expression)
    st = ScopeTraversal(
        expression=select.unalias(),
        scope=scope,
    )
    logger.debug(
        "Yielding standard expression: '%s', Type: %s, Expr: %s, Id: %s",
        column,
        type(select.unalias()),
        select.sql(),
        id(st),
    )
    yield st


def walk_expressions_and_build_graph(
    generator: BaseGenerator,
    gen_ctx: GeneratorContext,
    pos_ctx: PositionContext,
) -> t.List[N]:
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
        parent_node, child_node = edge.parent, edge.child
        if parent_node:
            node_exists = gen_ctx.graph.has_node(parent_node.full_name)
            if not node_exists:
                nodes_created.append(parent_node)

            # Include any inherited columns
            inherited_columns_of_parent = find_inherited_columns_for_parent(
                column_node=parent_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
            )
            inherited_columns_of_child = find_inherited_columns_for_child(
                column_node=child_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
            )

            for parent in [parent_node] + inherited_columns_of_parent:
                for child in [child_node] + inherited_columns_of_child:
                    add_nodes_with_edge_to_graph(
                        parent,
                        child,
                        gen_ctx.graph,
                        gen_ctx.query,
                        pos_ctx,
                    )
    return nodes_created


def find_inherited_columns_for_parent(
    column_node: N, generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext
) -> t.List[ColumnNode]:
    """
    Find the inherited columns for a particular column, but only for the form 'SELECT FROM ONLY <table>'
    TODO fix comments etc
    """
    if not isinstance(column_node, ColumnNode) or column_node.parent_kind == TableType.CTE:
        return []

    # Find the column's exp.Table in the expression and check if it has 'ONLY' set
    if not column_node.expr.parent_select:
        return []

    inherited_columns = []
    for table in column_node.expr.parent_select.find_all(exp.Table):
        if table.catalog == column_node.catalog and table.db == column_node.schema and table.name == column_node.table:
            parent_table = table
            if parent_table.args.get("only", False):
                inherited_columns = []
            else:
                inherited_columns = find_inherited_columns(
                    column_node=column_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
                )
                logger.debug(f"Including inherited columns as sources: {[c.friendly_name for c in inherited_columns]}")

    return inherited_columns


def find_inherited_columns_for_child(
    column_node: N | None, generator: BaseGenerator, gen_ctx: GeneratorContext, pos_ctx: PositionContext
) -> t.List[ColumnNode]:
    """
    Find the inherited columns for a particular column, but only for the form 'MERGE|UPDATE ONLY <table>'
    """
    inherited_columns = []
    if not isinstance(column_node, ColumnNode) or column_node.parent_kind == TableType.CTE:
        return inherited_columns

    original_query = gen_ctx.query.get_original_self()
    if isinstance(original_query, UpdateQuery) and not getattr(original_query, "only", False):
        inherited_columns = find_inherited_columns(
            column_node=column_node, generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx
        )
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
    table_query = gen_ctx.query.object_mapping.lookup_table_query(table=table)

    # Collect any columns from inherited tables with the same name
    for inh_table in getattr(table_query, "inherited_by", []):
        col_def = [c for c in inh_table.get_column_defs() if c.name == column_node.name][0]
        col = util.column_def_to_column(column_def=col_def, parent_table=inh_table.get_target_as_table())
        col_ctx = gen_ctx.new(expr=col, scope=None)  # Remove the node so that the column isn't renamed
        for edge in generator.process_column(col, col_ctx, pos_ctx):
            inh_node_attrs = edge.parent
            inherited_column_nodes.append(inh_node_attrs)

    return inherited_column_nodes


def add_nodes_with_edge_to_graph(
    parent_node: N | None,
    child_node: N | None,
    graph: nx.MultiDiGraph,
    query: Q,
    pos_ctx: PositionContext,
):
    """
    Add two node and an edge between them to the graph.
    """
    p_attrs = add_node_if_not_exists(parent_node, graph)
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
        logger.debug("Skipping edge creation as both node already exist.")


def add_node_if_not_exists(node_attrs: N | None, graph: nx.MultiDiGraph) -> N | None:
    """
    Add a node to the graph if it doesn't already exist.

    We need to re-use the existing node attributes so that the edge attribute models don't refer to
    different-but-same-named node attributes.
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


def get_expression_for_column(column: exp.Column | int, expr: E) -> E:
    """
    Get the expression that matches the given column name.
    e.g. given "SELECT 1 AS a, 2 AS b", column 'b' maps to expression 2.
    """
    if isinstance(column, int):
        # The index of the query in "SELECT 1 UNION SELECT 2"
        select = getattr(expr, "selects")[column]
    else:
        if isinstance(expr, exp.Lateral):
            selects = [expr]
        else:
            # Common path
            selects = [select for select in getattr(expr, "selects") if select.alias_or_name == column.name]

        if len(selects) > 1:
            message = f"Column reference '{column}' is ambiguous ({len(selects)} possible options)"
            raise exception.SqlLeafException(message)

        if selects:
            select = selects[0]
        else:
            select = expr
    return t.cast(E, select)


@dataclass(frozen=True)
class ScopeTraversal:
    expression: exp.Expr
    scope: TableOrScopeType


def get_column_index(column: exp.Column | int, expr: exp.Expr):
    index = (
        column
        if isinstance(column, int)
        else next(
            (i for i, sel in enumerate(getattr(expr, "selects")) if sel.alias_or_name == column.name),
            -1,  # mypy will not allow a None here, but a negative index should never be returned
        )
    )
    if index == -1:
        col_name = column if isinstance(column, int) else column.name
        raise exception.SqlLeafException(message=f"Could not find {col_name} in {expr}")
    return index


# def set_cte_properties(path: t.List[ScopeTraversal]) -> None:
#     """
#     Check for properties related to recursive CTEs.
#
#     Make the first node recursive if anything in its path is also recursive.
#     Otherwise, we set it to be the anchor, as its children are the anchor part
#     of the expression.
#     """
#     root_node: ScopeTraversal = path[0]
#     if root_node.is_parent_a_recursive_cte:
#         for n in path[1:]:
#             if is_node_inside_a_recursive_cte(n):
#                 if n.is_parent_a_recursive_cte:
#                     root_node.recursive_cte_member_kind = "recursive"
#                     n.recursive_cte_member_kind = "anchor"
#                 else:
#                     root_node.recursive_cte_member_kind = "anchor"
#             break


# def is_node_inside_a_recursive_cte(expr: exp.Expr) -> bool:
#     """
#     Check if we're inside a recursive CTE
#     """
#     if parent_cte := expr.find_ancestor(exp.CTE):
#         if parent_cte.parent.recursive:
#             return True
#     return False


def check_for_trigger(
    table: exp.Table | exp.Literal | exp.Identifier | exp.Schema, object_mapping: mappings.ObjectMapping
) -> bool:
    """
    Check if a trigger overrides the query's behaviour.
    """
    if not isinstance(table, exp.Table):
        return False

    if trigger := object_mapping.lookup_trigger_query(table=table):
        if getattr(trigger, "timing", None) == "INSTEAD OF":
            logger.debug(
                "Skipping lineage for all columns of table '%s' since trigger '%s' overrides it."
                % (exp.table_name(table), getattr(trigger, "name", ""))
            )
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

    if query.dialect == "snowflake" and isinstance(query, PutQuery):
        expr = query.statement
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

    if query.dialect in ["athena", "redshift"] and isinstance(query, TableQuery) and query.property == "external":
        location_expr = query.location

        for child_node, _ in generator.iter_child_nodes(gen_ctx, pos_ctx):
            if child_node:
                gen_ctx = gen_ctx.new(expr=location_expr, child_node=child_node)
                pos_ctx = pos_ctx.new(select_index=child_node.ctx.select_index)
                walk_expressions_and_build_graph(generator=generator, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        return True
    return False
