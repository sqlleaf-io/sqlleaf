import logging
import json
import typing as t
import networkx as nx

from sqlleaf import mappings, util, path, types
from sqlleaf.objects.query_types import Query, InsertQuery, UpdateQuery, ViewQuery, CopyQuery, PutQuery, CTASQuery, ProcedureQuery, TableQuery
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes, GraphAttributes
from sqlleaf.path import LineagePath
from sqlleaf.processors import collector, transformer, generator

logger = logging.getLogger("sqlleaf")

QUERIES_WITH_LINEAGE = (InsertQuery, UpdateQuery, ViewQuery, CTASQuery, PutQuery, CopyQuery, TableQuery)


class Lineage:
    """
    Holds the lineage as a networkx graph.
    """

    def __init__(self):
        self.graph = new_graph()  # The graph that contains all lineage
        self.subgraphs: t.List[nx.MultiDiGraph] = []  # The subgraphs that make up the main graph
        self.paths: t.Dict[str, t.List[LineagePath]] = {}  # The paths throughout the graph
        self.object_mapping = None

    def generate(self, sql: str, dialect: str):
        """
        Generate lineage for one or more SQL statements.
        """
        self.init_mapping(dialect=dialect)

        parent_queries = collector.collect_queries(sql, dialect, self.object_mapping)

        for parent_query in parent_queries:
            graph = new_graph()
            queries = parent_query.get_all_queries()

            for query in queries:
                # Transform every query, but only produce lineage for certain ones
                if query_has_lineage(query):
                    transformer.transform_query(query, self.object_mapping)
                    generator.generate_column_lineage_for_query(query, graph, self.object_mapping)
                query.set_to_original()

            graph.graph["attrs"].add_query(parent_query)

            # Associate the query with the graph even if it has no lineage
            self.merge_graph(graph)
            self.graph.graph["attrs"].add_query(parent_query)
            types.update_column_data_types(self.graph)

    def merge_graph(self, subgraph: nx.MultiDiGraph):
        """
        Merge the subgraph into the main graph, and also track the individual subgraphs.
        """
        self.subgraphs.append(subgraph)

        for n, data in subgraph.nodes(data=True):
            if self.graph.has_node(n):
                old_node_attrs = self.graph.nodes[n]["attrs"]

                # The incoming graph's edges must have their NodeAttributes updated to match the existing graph's NodeAttributes.
                # This is because different graphs with identical Nodes will have different NodeAttributes Python objects.
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

    def get_nodes(self) -> t.List[NodeAttributes]:
        nodes = [data["attrs"] for n, data in self.graph.nodes(data=True)]
        # TODO: sort on full_name?
        nodes = sorted(nodes, key=lambda e: (e.catalog, e.schema, e.table, e.column))
        return nodes

    def get_queries(self) -> t.List[Query]:
        """
        Get the queries from each of the subgraphs.
        """
        return self.graph.graph["attrs"].queries

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

    def print_json(self):
        nodes = self.get_nodes()
        edges = self.get_edges()
        queries = self.get_queries()
        sps = self.get_stored_procedures()
        paths = self.get_paths()

        _nodes = [n.to_dict() for n in nodes]
        _edges = [e.to_dict() for e in edges]
        _queries = [q.to_dict() for q in queries]
        _sps = [s.to_dict() for s in sps]
        _paths = [p.to_dict() for p in paths]

        print(
            json.dumps(
                {
                    "nodes": _nodes,
                    "edges": _edges,
                    "queries": _queries,
                    "stored_procedures": _sps,
                    "paths": _paths,
                },
                indent=2,
            )
        )

    def print_tree(self, full_name=False):
        """
        Print from the leaves to the root (as left to right) so that the tree is displayed correctly.
        For example:

        INSERT INTO fruit.processed
        SELECT SUBSTRING(name, 2, 4) AS name
        FROM fruit.raw

        Output:

        fruit.processed.name
        └── SUBSTRING()
            ├── fruit.raw.name
            ├── 2
            └── 4
        """
        g = self.graph.reverse()  # We print from the leaves to the roots
        root_columns = util.get_root_nodes(g)
        seen = set()
        symbol = "└──"

        attr = "full_name" if full_name else "friendly_name"

        # TODO: this may not be needed since the NodeAttributes are nodes
        for i, root in enumerate(root_columns):
            for depth, edge_attrs in util.find_edges_downward(g, root):  # TODO: fetch edges in order of function argument index
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
          column[fruit.raw.apple] -> function[UPPER()] - column[fruit.processed.apple]
        """
        for _path in self.get_paths():
            nodes = _path.node_hops()

            for i, node in enumerate(nodes):
                print(node.friendly_name, end="")
                if i < len(nodes) - 1:
                    print(" -> ", end="")
                else:
                    print("\n")

    def init_mapping(self, dialect: str):
        if not self.object_mapping:
            self.object_mapping = mappings.ObjectMapping(dialect=dialect)
            return


def new_graph() -> nx.MultiDiGraph:
    """
    A graph has attributes along with its node and edges.
    """
    return nx.MultiDiGraph(attrs=GraphAttributes())


def query_has_lineage(query: Query) -> bool:
    """
    Check if a query has lineage within its expressions.
    """
    has_lineage = True
    if not isinstance(query, QUERIES_WITH_LINEAGE):
        has_lineage = False
    elif isinstance(query, CTASQuery) and not query.with_data:
        has_lineage = False
    elif isinstance(query, TableQuery) and query.property != "external":
        has_lineage = False

    if not has_lineage:
        logger.debug(f"Query type '{query.__class__.__name__}' does NOT have lineage. Skipping.")
    return has_lineage
