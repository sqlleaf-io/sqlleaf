import logging
import typing as t

import networkx as nx

from sqlleaf import mappings, path, typing, util
from sqlleaf.mappings import ObjectMapping
from sqlleaf.models.node import EdgeAttributes, GraphAttributes, N
from sqlleaf.models.query import (
    CopyQuery,
    CTASQuery,
    InsertQuery,
    MultitableInsertQuery,
    ProcedureQuery,
    PutQuery,
    Q,
    QueryHolder,
    TableQuery,
    UnloadQuery,
    UpdateQuery,
    UserDefinedFunctionQuery,
    ViewQuery,
)
from sqlleaf.path import LineagePath
from sqlleaf.processors import collector
from sqlleaf.processors.generators import generator
from sqlleaf.processors.transformers import transformer
from sqlleaf.typing import SqlObjectType

logging.getLogger("sqlglot").setLevel(logging.WARNING)
logger = logging.getLogger("sqlleaf")


class Lineage:
    """
    Holds the lineage as a networkx graph.
    """

    def __init__(self):
        self.graph = new_graph()  # The graph that contains all lineage
        self.subgraphs: t.List[nx.MultiDiGraph] = []  # The subgraphs that make up the main graph
        self.paths: t.Dict[str, t.List[LineagePath]] = {}  # The paths throughout the graph
        self.object_mapping: ObjectMapping | None = None
        self.collected_queries: collector.CollectQueryResult | None = None

    def generate(self, sql: str, dialect: str, **opts: t.Unpack[typing.IncludeNodesArgs]):
        """
        Generate lineage for one or more SQL statements.
        """
        object_mapping = self.init_mapping(dialect=dialect)
        self.collected_queries = collector.collect_queries(sql, dialect, object_mapping)

        for parent_holder in self.collected_queries.queries:
            # A parent holder wraps a top-level query, possibly containing child holders
            graph = new_graph()

            # Phase 2: Transformer — transformation only (substitution done at collection time)
            for holder in parent_holder.get_all_holders():
                if should_process_holder(holder):
                    transformer.transform_query(holder, dialect, object_mapping)

            all_holders = parent_holder.get_all_holders()

            if not all_holders:
                continue

            # Phase 3: Generate lineage only for qualifying holders
            for holder in all_holders:
                # MultitableInsertQuery should not have lineage generated for it directly
                # as it is not a SELECT-based query. Its children (InsertQuery) will
                # have lineage generated instead.
                if isinstance(holder.original, MultitableInsertQuery):
                    continue

                # Transform and produce lineage only for certain queries
                if query_has_lineage(holder.original) and should_process_holder(holder):
                    generator.generate_lineage_for_query(holder, graph)

            # Associate the query with the graph even if it has no lineage
            graph.graph["attrs"].add_query_to_graph(parent_holder)
            self.merge_graph(graph)
            self.graph.graph["attrs"].add_query_to_graph(parent_holder)
            # types.update_column_data_types(self.graph)
            logger.debug("---")

    def merge_graph(self, subgraph: nx.MultiDiGraph):
        """
        Merge the subgraph into the main graph, and also track the individual subgraphs.
        """
        self.subgraphs.append(subgraph)

        for n, data in subgraph.nodes(data=True):
            if self.graph.has_node(n):
                old_node_attrs = self.graph.nodes[n]["attrs"]

                # The incoming graph's edges must have their NodeAttributes updated to
                # match the existing graph's NodeAttributes.
                # This is because different graphs with identical Nodes will have different NodeAttributes models.
                for par, chi, edge_data in subgraph.edges(data=True):
                    # Overwrite the new edge's Node to be the old Node
                    if edge_data["attrs"].parent.full_name == n:
                        edge_data["attrs"].parent = old_node_attrs
                    if edge_data["attrs"].child.full_name == n:
                        edge_data["attrs"].child = old_node_attrs
            else:
                self.graph.add_node(n, **data)

        self.graph.add_edges_from(subgraph.edges(data=True))

    def get_edges(self) -> t.List[EdgeAttributes]:
        edges = [data["attrs"] for par, chi, data in self.graph.edges(data=True)]
        edges = sorted(edges, key=lambda e: (e.parent.full_name, e.child.full_name))
        for edge in edges:
            logger.debug(f"Edge: {edge.parent.friendly_name} -> {edge.child.friendly_name}")
        return edges

    def get_nodes(self) -> t.List[N]:
        nodes = [data["attrs"] for n, data in self.graph.nodes(data=True)]
        # TODO: sort on selected index?
        nodes = sorted(
            nodes, key=lambda e: (getattr(e, "catalog", ""), getattr(e, "schema", ""), getattr(e, "table", ""), e.name)
        )
        return nodes

    def get_original_queries(self) -> t.List[Q]:
        """
        Get the original queries from the graph.
        """
        return [q.original for q in self.graph.graph["attrs"].queries]

    def get_transformed_queries(self) -> t.List[Q]:
        """
        Get the transformed queries from the graph.
        """
        return [q.transformed for q in self.graph.graph["attrs"].queries]

    def get_stored_procedures(self):
        """
        Get the stored procedures from each of the edges.
        """
        return []

    def get_paths(self) -> t.Generator[LineagePath]:
        """
        paths: [
            {
                "id": "",
                "length": 2,
                "hops": [
                    "edge1",
                    "edge2
                ]
            }
        ]
        """
        for p in path.find_all_paths(graph=self.graph):
            yield p

    # def print_json(self):
    #     nodes = self.get_nodes()
    #     edges = self.get_edges()
    #     queries = self.get_original_queries()
    #     sps = self.get_stored_procedures()
    #     paths = self.get_paths()
    #
    #     _nodes = [n.to_dict() for n in nodes]
    #     _edges = [e.to_dict() for e in edges]
    #     _queries = [q.to_dict() for q in queries]
    #     _sps = [s.to_dict() for s in sps]
    #     _paths = [p.to_dict() for p in paths]
    #
    #     print(
    #         json.dumps(
    #             {
    #                 "node": _nodes,
    #                 "edges": _edges,
    #                 "queries": _queries,
    #                 "stored_procedures": _sps,
    #                 "paths": _paths,
    #             },
    #             indent=2,
    #         )
    #     )

    def print_tree(self, full_name=False):
        """
        Print from the leaves to the root (as left to right) so that the tree is displayed correctly.
        For example:

        INSERT INTO fruit.processed
        SELECT SUBSTRING(name, 2, 4) AS name
        FROM fruit.raw

        Output:

        column[fruit.processed.name]
        └── function[SUBSTRING]
            ├── column[fruit.raw.name]
            ├── literal[2]
            └── literal[4]
        """
        g = self.graph.reverse()  # We print from the leaves to the roots
        root_columns = util.get_root_nodes(g)
        seen = set()
        symbol = "└──"

        attr = "full_name" if full_name else "friendly_name"

        # TODO: this may not be needed since the NodeAttributes are node
        for i, root in enumerate(root_columns):
            for depth, edge_attrs in util.find_edges_downward(
                g, root
            ):  # TODO: fetch edges in order of function argument index
                # Swap the parent and child
                parent_name = edge_attrs.child.full_name
                child_name = edge_attrs.parent.full_name
                num_descendents_of_child = len(nx.descendants(g, child_name))

                parent_node = g.nodes[parent_name]["attrs"]
                child_node = g.nodes[child_name]["attrs"]

                if parent_name not in seen:
                    symbol = "└──"

                    # Print arrows
                    if depth > 0:
                        prefix = ((depth - 1) * 4 * " ") + f"{symbol} "
                    else:
                        prefix = ""
                    print("%s%s" % (prefix, getattr(parent_node, attr)))
                seen.add(parent_name)

                # Print the child if we're at the end of the path
                if num_descendents_of_child == 0:
                    if depth == 0:
                        # Direct load (source -> target)
                        prefix = "└── "
                    else:
                        prefix = (depth * 4 * " ") + f"{symbol} "
                    print("%s%s" % (prefix, getattr(child_node, attr)))
                    seen.add(child_name)

    def print_paths(self):
        """
        Iterate over all the paths in the graph and print each one.

        Example output:
          column[fruit.raw.apple] -> function[UPPER] - column[fruit.processed.apple]
        """
        for _path in self.get_paths():
            nodes = _path.node_hops()
            path = ""

            for i, node in enumerate(nodes):
                path += node.friendly_name
                if i < len(nodes) - 1:
                    path += " -> "
            print(path)

    def init_mapping(self, dialect: str) -> mappings.ObjectMapping:
        if self.object_mapping is None:
            self.object_mapping = mappings.ObjectMapping(dialect=dialect)
        return self.object_mapping


def new_graph() -> nx.MultiDiGraph:
    """
    A graph has attributes along with its node and edges.
    """
    return nx.MultiDiGraph(attrs=GraphAttributes())


QUERIES_WITH_LINEAGE = (
    CTASQuery,
    CopyQuery,
    InsertQuery,
    MultitableInsertQuery,
    PutQuery,
    TableQuery,
    UnloadQuery,
    UpdateQuery,
    ViewQuery,
)


def query_has_lineage(query: Q) -> bool:
    """
    Check if a query has lineage within its expressions.

    We distinguish between a query's definition and a query that is called.
    That is, in order for a `CREATE FUNCTION` or `CREATE PROCEDURE` to have
    lineage, it must be executed by an invoking statement, e.g. `CALL()` or `SELECT UDF()`
    Simply having statements inside its definition is not sufficient to produce lineage.
    """
    has_lineage = True
    if not isinstance(query, QUERIES_WITH_LINEAGE):
        has_lineage = False
    elif isinstance(query, CopyQuery) and query.source_info.type == SqlObjectType.VALUES:
        # COPY TO STDOUT VALUES (..) # TODO: this should have lineage
        has_lineage = False
    elif isinstance(query, CopyQuery) and not query.is_query_active():
        has_lineage = False
    elif isinstance(query, CTASQuery) and not query.load_data:
        # CREATE TABLE WITH NO DATA
        has_lineage = False
    elif isinstance(query, CTASQuery) and query.source_info.type == SqlObjectType.PREPARED_STATEMENT:
        # CREATE TABLE AS EXECUTE
        has_lineage = False
    elif isinstance(query, TableQuery) and query.property != "external":
        # CREATE EXTERNAL TABLE
        has_lineage = False

    if not has_lineage:
        logger.debug(f"Query type '{query.__class__.__name__}' does NOT have lineage. Skipping.")
    return has_lineage


def should_process_holder(holder: QueryHolder) -> bool:
    """
    Check if a query holder should be processed (transformed or lineage generated).

    Template queries (descendants of a UDF or Procedure definition) should not be
    transformed or have lineage generated independently; they only contribute to
    lineage when they are substituted into an invoking statement.
    """
    if isinstance(holder.original, (UserDefinedFunctionQuery, ProcedureQuery)):
        return False

    curr = holder.parent_holder
    while curr:
        if isinstance(curr.original, (UserDefinedFunctionQuery, ProcedureQuery)):
            return False
        curr = curr.parent_holder

    return True
