from __future__ import annotations
import logging
import typing as t
from dataclasses import replace

import networkx as nx
import sqlglot
from sqlglot import exp

if t.TYPE_CHECKING:
    pass

from sqlleaf import (
    util,
    structs,
    mappings,
    sqlglot_lineage,
    transform,
)

logger = logging.getLogger("sqlleaf")


def transform_query(parent_query: structs.Query, object_mapping) -> structs.Query:
    """
    Transform the queries so that they have complete information in preparation for lineage calculation.
    """
    queries = parent_query.child_queries or [parent_query]

    # Process each of the statements
    for query in queries:
        statement = query.statement
        logger.info(f"Transforming query: {str(type(statement))}")

        # Apply sqlglot's optimize() functions to infer schemas, qualify columns, etc
        statement = transform.apply_optimizations(statement, query.dialect, object_mapping, query.child_table)

        # Simplify the expression tree if possible (e.g. always-true logical statements)
        statement = sqlglot.optimizer.optimizer.simplify(statement)

        # Transform CASE statements to remove false positive lineage; see docs
        statement = statement.transform(transform.case_statement_transformer)
        query.statement_transformed = statement
        query.set_statement(statement)

    return parent_query


def get_lineage_for_query(parent_query: structs.Query, object_mapping) -> nx.MultiDiGraph:
    """
    Calculate the column-level lineage for one or more SQL queries.

    The queries must be the top-level 'container' query, i.e. CREATE PROCEDURE, MERGE, etc.
    The individual queries (INSERT, UPDATE) are then extracted.
    """
    graph = structs.new_graph()
    graph.graph["attrs"].add_query(parent_query)
    queries = parent_query.child_queries or [parent_query]

    for query in queries:
        generate_column_lineage_for_query(query, graph, object_mapping)
        query.set_to_original()

    return graph


def generate_column_lineage_for_query(
    query: structs.Query,
    graph: nx.MultiDiGraph,
    object_mapping: mappings.ObjectMapping,
) -> nx.MultiDiGraph:
    """
    Calculate the lineage for an SQL query.

    We collect all the columns from the query's target table, and then iterate
    over sqlglot's abstract syntax tree (AST) to determine the set of nodes
    and transformations used along the path to reach the table's columns.

    Parameters:
        query: the Query to calculate lineage for
        child_columns: the table's columns, marked as selected in the query or not
        child_table: the child table
        dialect:
        object_mapping:
        statement_index: the statement's index within a list of statements [detects duplicates]
    """
    child_table = query.child_table
    statement = query.statement
    scope = sqlglot.optimizer.build_scope(statement)

    logger.info(f"Getting lineage for query: {statement.sql(comments=False)}")

    ctx = structs.NodeContext(statement_index=query.get_statement_index())
    processor_ctx = structs.ProcessorContext(
        graph=graph,
        object_mapping=object_mapping,
        query=query,
        expr=statement,
    )

    builder = structs.LineageBuilder.from_dialect(query.dialect)
    if isinstance(query, structs.PutQuery):
        # Short-circuit this function for simplicity
        builder.process_put(processor_ctx, ctx)
        return graph

    # Check if a trigger overrides the query's behaviour
    if t := object_mapping.find_query(kind='trigger', table=child_table):
        if t.timing == "INSTEAD OF":
            logger.debug("Skipping lineage for all columns of table '%s' since trigger '%s' overrides it." % (exp.table_name(child_table), t.name))
            # TODO: Use the trigger's function as the lineage
            func = t.execute

            return graph


    """
    For each child table column, calculate the lineage
    """
    # Ensure the child table exists with the expected columns
    child_columns = query.determine_selected_columns(object_mapping)
    select_idx = 0
    for col_name, col_props in child_columns.items():

        # TODO: refactor
        col_expr = exp.column(
            catalog=child_table.catalog,
            db=child_table.db,
            table=child_table.name,
            col=col_name,
        )
        col_expr.type = exp.DataType.build(col_props["kind"])
        col_expr.parent = child_table

        ctx = structs.NodeContext(select_index=select_idx, statement_index=query.get_statement_index())
        processor_ctx = replace(processor_ctx, expr=col_expr)

        child_node = structs.ColumnNode(
            catalog=child_table.catalog,
            schema=child_table.db,
            table=child_table.name,
            column=col_name,
            processor_ctx=processor_ctx,
            ctx=ctx,
        )

        if default_expr:= col_props["default"]:
            # Add the default column expression to the lineage
            # TODO: make this a CLI flag
            default_ctx = replace(processor_ctx, expr=default_expr, child_node_attrs=child_node)
            builder.walk_tree_and_build_graph(processor_ctx=default_ctx, ctx=ctx)

        if not col_props['selected']:
            continue

        logger.info(
            "Calculating lineage. Column: %s, Table: %s, Index: %s",
            col_name,
            child_table.name,
            select_idx,
        )

        # trim_selects=false -> 10x faster, skips re-parsing
        lin = sqlglot_lineage.lineage(
            column=col_name,
            sql=statement,
            scope=scope,
            dialect=query.dialect,
            schema=object_mapping,
            trim_selects=False,
        )

        """
        Collect the functions for each Node, and then extract the Node's Expression into a common object type
        that contains only the essential information we need.
        """
        for path in _get_all_paths_from_lineage(lin):
            set_cte_properties(path)

            child_node_attrs = child_node
            logger.debug("----")
            logger.debug(f"Found path from lineage.lineage(): {[(n.name, n.expression.sql()) for n in path]}")

            for node_depth, node in enumerate(path):
                logger.debug("----")
                # Node depth distinguishes identical queries across CTEs

                if isinstance(query, structs.CopyQuery) and query.is_target_a_stage:
                    # Set the column to be a StageNode (if applicable) since we now have the lineage from using the dummy column
                    processor_ctx = replace(processor_ctx, expr=query.target.this)
                    child_node_attrs = structs.StageNode(processor_ctx=processor_ctx, ctx=ctx)

                top_expr = util.unwrap_expression(node.expression)
                logger.debug(f"Processing node alias: '{node.name}', Expr: {top_expr}, Id: {id(node)}")
                logger.debug(f"Child node: {child_node_attrs.full_name}")

                child_ctx = replace(ctx, node_depth=node_depth)
                processor_ctx = replace(
                    processor_ctx,
                    expr=top_expr,
                    node=node,
                    child_node_attrs=child_node_attrs,
                )

                nodes = builder.walk_tree_and_build_graph(processor_ctx, child_ctx)
                if nodes:
                    logger.debug(f"Produced nodes: {[n.full_name for n in nodes]}")
                    # The next child is the most recently created parent
                    child_node_attrs = nodes[-1]

                    # Ensure the child for the next iteration supports children
                    # e.g. Literals cannot be children
                    for n in reversed(nodes):
                        if not n.expr.is_leaf():
                            child_node_attrs = n
                            break

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
            if sqlglot_lineage.is_node_inside_a_recursive_cte(n):
                if n.is_parent_a_recursive_cte:
                    root_node.recursive_cte_member_kind = 'recursive'
                    n.recursive_cte_member_kind = 'anchor'
                else:
                    root_node.recursive_cte_member_kind = 'anchor'
            break


def update_column_data_types(graph: nx.MultiDiGraph):
    """
    Update the column types of the nodes in the graph.

    Traverse each edge from the roots and:
    - Update the target column if its type is UNKNOWN by looking at the source column and its functions
    - Check if the source->target type conversion is compatible

    This is important for resolving column types of views, as multiple queries may have connected multiple views together whose
    types are by default UNKNOWN and therefore need resolution.
    """
    # TODO: Use sqlglot.expressions.DataType.is_type() as a first check
    logger.debug("Skipping data types as it's faulty")
    return

    root_columns = _get_root_nodes(graph)

    for i, root in enumerate(root_columns):
        for depth, edge_attrs in util.find_edges_downward(graph, root):
            parent_attrs = edge_attrs.parent
            child_attrs = edge_attrs.child
            # last_function_type = edge_attrs.get_last_function_type()
            last_function_type = ''
            dialect = edge_attrs.query.dialect

            ensure_correct_data_types(parent_attrs, child_attrs, last_function_type, dialect)


def ensure_correct_data_types(
    parent_attrs: structs.NodeAttributes,
    child_attrs: structs.NodeAttributes,
    last_function_type: str,
    dialect: str,
):
    """
    Check if the child column's type is compatible with its parent type or its outermost function's type.
    If we can determine the correct type for a child column, set it.
    Throw warnings if the types are incompatible.

    For example given,
        SELECT COUNT(LOWER(kind)) as cnt FROM fruit.raw;
    with columns:
        fruit.raw.kind => VARCHAR (from table)
        LOWER() => VARCHAR
        COUNT() => BIGINT
        cnt => INT (from table)
    We expect 'cnt' to be compatible with the outermost function (COUNT).
    """
    p_type = parent_attrs.data_type
    c_type = child_attrs.data_type
    logger.info(f"Checking type compatibility. Parent: {p_type}, Child: {c_type}, Last Function: {last_function_type}")

    # The last function takes precedence over the parent
    if last_function_type:
        if last_function_type == "UNKNOWN" and c_type == "UNKNOWN":
            # Do nothing
            pass
        elif last_function_type == "UNKNOWN" and c_type != "UNKNOWN":
            # Do nothing
            pass
        elif last_function_type != "UNKNOWN" and c_type == "UNKNOWN":
            # Set c_type <= last_function_type. This is key for resolving view types
            child_attrs.data_type = last_function_type
        elif last_function_type != "UNKNOWN" and c_type != "UNKNOWN":
            # Check if compatible
            are_types_compatible(subtyp=last_function_type, typ=c_type, dialect=dialect)
    else:
        # The child's type must be compatible with the parent's type
        if p_type == "UNKNOWN" and c_type == "UNKNOWN":
            # Do nothing
            pass
        elif p_type == "UNKNOWN" and c_type != "UNKNOWN":
            # Set p_type <= c_type. This is key for resolving view types
            parent_attrs.data_type = c_type
        elif p_type != "UNKNOWN" and c_type == "UNKNOWN":
            # Set p_type => c_type. This is key for resolving view types
            child_attrs.data_type = p_type
        elif p_type != "UNKNOWN" and c_type != "UNKNOWN":
            # Check if compatible
            are_types_compatible(subtyp=p_type, typ=c_type, dialect=dialect)

    p_type = parent_attrs.data_type
    c_type = child_attrs.data_type
    logger.info(f"New types. Parent: {p_type} Child: {c_type}")


def calculate_paths(graph: nx.MultiDiGraph) -> t.Dict[str, structs.LineagePath]:
    """
    Find all the unique paths in the graph and give each path a unique ID according to the set of edges it contains.

    This only makes sense if multiple procedures / multiple graphs need to be merged. This is because the root of a path
    in a graph may change whenever a new graph is merged. TODO: is this true? remove?

    An edge may belong to multiple paths. This usually indicates a conflict in the ETL processes (e.g. a table's column
    with two sources of INSERTs) but it may still be valid in certain cases (such as re-using a table in different stored procedures)
    so we permit it.
    """
    all_lineage_paths = {}
    root_columns = _get_root_nodes(graph)

    for i, root in enumerate(root_columns):
        for path in util.find_edge_paths(graph, root):
            if not path:
                continue

            logger.debug("Found edge path: %s", [e.id for e in path])
            lineage_path = structs.LineagePath(root=root, hops=path)
            all_lineage_paths[lineage_path.path_id] = lineage_path

    return all_lineage_paths


def _get_root_nodes(graph: nx.MultiDiGraph) -> t.List[str]:
    return [n for n in graph.nodes if graph.in_degree(n) == 0 and graph.out_degree(n) > 0]


def _get_node_leaves(expr: exp.Expression):
    excl_types = (exp.DataType, exp.Var, exp.Table, exp.Column, exp.Identifier)
    leaves = [l for l in expr.walk() if l.is_leaf() and not isinstance(l, excl_types)]
    return leaves


def _get_all_paths_from_lineage(node: sqlglot_lineage.Node, path=None):
    """
    Iterate over the tree of lineage.Node produced by lineage.lineage()

    NOTE: the path is just a list! It is completely separate from the concept of a path in a graph.
    """
    if path is None:
        path = []

    path.append(node)
    expr = util.unwrap_expression(node.expression)

    if isinstance(expr, exp.Window):
        # Short circuit window functions so that false positive lineage isn't included
        yield path

    elif not node.downstream:
        yield path

    else:
        for child in node.downstream:
            yield from _get_all_paths_from_lineage(child, path)

    path.pop()

def are_types_compatible(subtyp: str, typ: str, dialect: str) -> bool:
    """
    Check if two types are compatible. Type `subtyp` must be equal or less than `typ`.
    For example, SMALLINT is compatible with BIGINT, but not vice versa.
    """
    # logger.info(f"Checking type compatibility between type '{typ}' and subtype '{subtyp}'")

    compatibility_matrix = {
        "postgres": {
            # Postgres performs implicit casts
            "SMALLINT": [
                "SMALLINT",
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "BOOLEAN",
            ],
            "INT": [
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "BOOLEAN",
                "SMALLINT",
            ],
            "BIGINT": [
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "BOOLEAN",
                "SMALLINT",
                "INT",
            ],
            "NUMERIC": [
                "NUMERIC",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "SMALLINT",
                "INT",
                "BIGINT",
                "REAL",
                "DOUBLE PRECISION",
                "DATE",
                "TIME",
                "TIMESTAMP",
            ],
            "REAL": [
                "REAL",
                "DOUBLE PRECISION",
                "NUMERIC",
                "SMALLINT",
                "INT",
                "BIGINT",
                "CHAR",
                "VARCHAR",
                "TEXT",
            ],
            "DOUBLE PRECISION": [
                "DOUBLE PRECISION",
                "REAL",
                "NUMERIC",
                "SMALLINT",
                "INT",
                "BIGINT",
                "CHAR",
                "VARCHAR",
                "TEXT",
            ],
            "CHAR": [
                "CHAR",
                "VARCHAR",
                "TEXT",
                "SMALLINT",
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "BOOLEAN",
                "DATE",
                "TIME",
                "TIMESTAMP",
            ],
            "VARCHAR": [
                "VARCHAR",
                "CHAR",
                "TEXT",
                "SMALLINT",
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "BOOLEAN",
                "DATE",
                "TIME",
                "TIMESTAMP",
            ],
            "TEXT": [
                "TEXT",
                "CHAR",
                "VARCHAR",
                "SMALLINT",
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "BOOLEAN",
                "DATE",
                "TIME",
                "TIMESTAMP",
            ],
            "BOOLEAN": [
                "BOOLEAN",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "SMALLINT",
                "INT",
                "BIGINT",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "DATE",
                "TIME",
                "TIMESTAMP",
            ],
            "DATE": [
                "DATE",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "TIMESTAMP",
                "TIME",
                "SMALLINT",
                "INT",
                "BIGINT",
                "BOOLEAN",
            ],
            "TIME": [
                "TIME",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "DATE",
                "TIMESTAMP",
                "SMALLINT",
                "INT",
                "BIGINT",
                "BOOLEAN",
            ],
            "TIMESTAMP": [
                "TIMESTAMP",
                "DATE",
                "TIME",
                "NUMERIC",
                "REAL",
                "DOUBLE PRECISION",
                "CHAR",
                "VARCHAR",
                "TEXT",
                "SMALLINT",
                "INT",
                "BIGINT",
                "BOOLEAN",
            ],
            "BYTEA": ["BYTEA", "TEXT", "CHAR", "VARCHAR"],
            "UUID": ["UUID", "TEXT", "CHAR", "VARCHAR"],
            "JSON": ["JSON", "JSONB"],
            "JSONB": ["JSONB", "JSON"],
            "INET": ["INET", "TEXT", "CHAR", "VARCHAR"],
            "MACADDR": ["MACADDR", "TEXT", "CHAR", "VARCHAR"],
        },
        "redshift": {
            "SMALLINT": [
                "INT",
                "BIGINT",
                "DECIMAL",
                "REAL",
                "DOUBLE PRECISION",
                "VARCHAR",
            ],
            "INT": ["BIGINT", "DECIMAL", "REAL", "DOUBLE PRECISION", "VARCHAR"],
            "BIGINT": ["DECIMAL", "REAL", "DOUBLE PRECISION", "VARCHAR"],
            "DECIMAL": ["REAL", "DOUBLE PRECISION", "VARCHAR"],
            "REAL": ["DOUBLE PRECISION", "VARCHAR"],
            "DOUBLE PRECISION": ["VARCHAR"],
            "BOOLEAN": ["VARCHAR"],
            "CHAR": ["VARCHAR"],
            "VARCHAR": [],
            "DATE": ["TIMESTAMP", "VARCHAR"],
            "TIMESTAMP": ["VARCHAR"],
            "TIMESTAMPTZ": ["TIMESTAMP", "VARCHAR"],
            "TIME": ["VARCHAR"],
            "TIMETZ": ["TIME", "VARCHAR"],
            "VARBYTE": ["VARCHAR"],
            "SUPER": ["VARCHAR"],
        },
    }
    # TODO: add warnings to global tracker
    types = compatibility_matrix[dialect]
    if typ != subtyp and typ not in types[subtyp]:
        print(f"Warning: type {subtyp} is not compatible with {typ}")
        return False
    return True
