from __future__ import annotations
import logging
import typing as t
from dataclasses import replace

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import build_scope

if t.TYPE_CHECKING:
    pass

from sqlleaf import (
    mappings,
    sqlglot_lineage,
    exception,
)

from sqlleaf.objects.query_types import Query, InsertQuery, UpdateQuery, ViewQuery, CopyQuery, PutQuery, CTASQuery
from sqlleaf.objects.context import ProcessorContext, NodeContext
from sqlleaf.objects.node_types import ColumnNode, new_graph
from sqlleaf.processors.generator import LineageGenerator
from sqlleaf.processors import transformer

logger = logging.getLogger("sqlleaf")

QUERIES_WITH_LINEAGE = (InsertQuery, UpdateQuery, ViewQuery, CTASQuery, PutQuery, CopyQuery)


def get_lineage_for_query(query: Query, object_mapping: mappings.ObjectMapping) -> nx.MultiDiGraph:
    """
    Calculate the column-level lineage for one or more SQL queries.

    The queries must be the top-level 'container' query, i.e. CREATE PROCEDURE, MERGE, etc.
    The individual queries (INSERT, UPDATE) are then extracted.
    """
    graph = new_graph()
    queries = query.get_all_queries()

    for query in queries:
        # Transform every query, but only produce lineage for certain ones
        if isinstance(query, QUERIES_WITH_LINEAGE):
            transformer.transform_query(query, object_mapping)
            generate_column_lineage_for_query(query, graph, object_mapping)
        query.set_to_original()

    graph.graph["attrs"].add_query(query)
    return graph


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

    builder = LineageGenerator.from_dialect(query.dialect)
    if isinstance(query, PutQuery):
        # Short-circuit this function; it's not an insert
        builder.process_put(processor_ctx, ctx)
        return graph

    # Check if a trigger overrides the query's behaviour
    if trigger := object_mapping.find_query(kind="trigger", table=child_table):
        if trigger.timing == "INSTEAD OF":
            logger.debug("Skipping lineage for all columns of table '%s' since trigger '%s' overrides it." % (exp.table_name(child_table), t.name))
            # TODO: Use the trigger's function as the lineage
            #func = trigger.execute

            return graph

    # Copy since lineage() transforms columns for generate() to work (see c.set()). TODO: Move all transforms into transform()
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
            builder.walk_tree_and_build_graph(processor_ctx=constraint_ctx, ctx=ctx)

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
        builder.walk_query_and_build_graph(child_node, scope, processor_ctx, ctx, node_depth=0)
        select_idx += 1

    return graph


def set_cte_properties(path: t.List[sqlglot_lineage.Node]) -> None:
    """
    Check for properties related to recursive CTEs.

    Make the first node recursive if anything in its path is also recursive.
    Otherwise, we set it to be the anchor, as its children are the anchor part
    of the expression.
    """
    root_node: sqlglot_lineage.Node = path[0]
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
