import json
import logging
import typing as t

from networkx import MultiDiGraph

from sqlleaf import exception, mappings, path
from sqlleaf.models.hook import Hook
from sqlleaf.models.node import EdgeAttributes, GraphAttributes, N, NodeAttributes
from sqlleaf.models.query import Q
from sqlleaf.processors.collector import collector
from sqlleaf.processors.generator import generator

logging.getLogger("sqlglot").setLevel(logging.WARNING)
logger = logging.getLogger("sqlleaf")


class Lineage:
    """
    Holds the lineage as a networkx graph.
    """

    def __init__(self):
        self.graph = new_graph()  # The graph that contains all lineage
        self.subgraphs: list[MultiDiGraph] = []  # The subgraphs that make up the main graph
        self.collected_queries = collector.CollectQueryResult()
        self.user_defined_hooks: list[Hook] = []
        self.object_mapping: mappings.ObjectMapping | None = None

    def generate(self, sql: str, dialect: str, on_error: str = "error") -> None:
        """
        Generate lineage for one or more SQL statements.
        """
        exception.set_error_action(action=on_error)

        self.init_object_mapping(dialect)

        self.collected_queries = collector.collect_queries(
            text=sql, dialect=dialect, object_mapping=self.object_mapping
        )

        for parent_holder in self.collected_queries.queries:
            # A parent holder wraps a top-level query, possibly containing downstream holders
            graph = new_graph()
            query_holders = parent_holder.get_all_holders()

            for holder in query_holders:
                # Produce lineage only for certain queries
                if generator.query_has_lineage(holder.original):
                    generator.generate_lineage_for_query(holder, graph, self.user_defined_hooks)

            # Associate the query with the graph even if it has no lineage
            graph.graph["attrs"].add_query_to_graph(parent_holder)
            self.merge_graph(graph)
            self.graph.graph["attrs"].add_query_to_graph(parent_holder)

    def merge_graph(self, subgraph: MultiDiGraph) -> None:
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
                self.object_mapping.node_index.add(data["attrs"])

        self.graph.add_edges_from(subgraph.edges(data=True))

    def get_edges(self) -> list[EdgeAttributes]:
        edges = [data["attrs"] for par, chi, data in self.graph.edges(data=True)]
        edges = sorted(edges, key=lambda e: (e.parent.full_name, e.child.full_name))
        for edge in edges:
            logger.debug(f"Found edge: {edge.parent.friendly_name} -> {edge.child.friendly_name}")
        return edges

    def get_nodes(self) -> list[N]:
        nodes = [data["attrs"] for n, data in self.graph.nodes(data=True)]
        # TODO: sort on selected index?
        nodes = sorted(
            nodes, key=lambda e: (getattr(e, "catalog", ""), getattr(e, "schema", ""), getattr(e, "table", ""), e.name)
        )
        return nodes

    def find_nodes(self, *nodes: NodeAttributes) -> list[NodeAttributes]:
        """
        Find a set of nodes in the graph matching the given node instances.

        This allows nodes to be found without knowing their positions.

        This uses an index/map structure because the keys of the full node names contain
        the positions of each node to identify them uniquely. For example, two literal
        expressions for "abc" are assigned their own positions to distinguish them from each other.

        Examples:
            # Find all columns whose name is 'price'
            find_nodes(ColumnNode(column="price"))

            # Find two columns: one unqualified, another fully qualified
            find_nodes(ColumnNode(column="age"), ColumnNode(schema="fruit", table="raw", column="name"))

            # Find all functions
            find_nodes(FunctionNode())
        """
        if self.object_mapping is None:
            return []

        found: list[NodeAttributes] = []
        seen: set[str] = set()

        for query in nodes:
            candidates = self.object_mapping.node_index.get(type(query))
            if query.name != "":
                query_name = query.get_name()
                candidates = [node for node in candidates if node.get_name() == query_name]

            for node in candidates:
                if node.full_name not in seen:
                    seen.add(node.full_name)
                    found.append(node)

        return found

    def paths_downstream_from(self, node: NodeAttributes) -> t.Generator[path.LineagePath]:
        """
        Find all the paths that begin with the given node.

        The node is looked up with `find_nodes()`, so a partial node matches every node with the same name.

        Examples:
            # Find every path downward from a column
            paths_downstream_from(ColumnNode(column="price"))
        """
        for start in self.find_nodes(node):
            for hops in path.find_edges_from_root(self.graph, start.full_name):
                if hops:
                    yield path.LineagePath(hops=hops)

    def paths_upstream_from(self, node: NodeAttributes) -> t.Generator[path.LineagePath]:
        """
        Find all the paths that end with the given node as their leaf.

        The reverse of `paths_downstream_from()`. The node is looked up with `find_nodes()`, so a partial node
        matches every node with the same name.

        Examples:
            # Find every path upward from a column
            paths_upstream_from(ColumnNode(column="total"))
        """
        reversed_graph = self.graph.reverse(copy=False)
        for end in self.find_nodes(node):
            for hops in path.find_edges_from_root(reversed_graph, end.full_name):
                if hops:
                    yield path.LineagePath(hops=list(reversed(hops)))

    def has_path(self, src: NodeAttributes, dst: NodeAttributes) -> bool:
        """
        Check whether there is a path from any node matching the first node to any node matching the second.

        Examples:
            # Check whether price flows into total
            has_path(ColumnNode(column="price"), ColumnNode(column="total"))
        """
        from networkx import has_path as nx_has_path

        return any(
            nx_has_path(self.graph, s.full_name, d.full_name)
            for s in self.find_nodes(src)
            for d in self.find_nodes(dst)
            if self.graph.has_node(s.full_name) and self.graph.has_node(d.full_name)
        )

    def paths_between_nodes(self, src: NodeAttributes, dst: NodeAttributes) -> t.Generator[path.LineagePath]:
        """
        Find all the paths that begin with a node matching the first node and end with a node matching the second.

        Examples:
            # Find every path from price to total
            paths_between_nodes(ColumnNode(column="price"), ColumnNode(column="total"))
        """
        dst_names = {d.full_name for d in self.find_nodes(dst)}

        for p in self.paths_downstream_from(src):
            if p.hops[-1].child.full_name in dst_names:
                yield p

    def get_original_queries(self) -> list[Q]:
        """
        Get the original queries from the graph.
        """
        return [q.original for q in self.graph.graph["attrs"].queries]

    def get_transformed_queries(self) -> list[Q]:
        """
        Get the transformed queries from the graph.
        """
        return [q.transformed for q in self.graph.graph["attrs"].queries]

    def get_paths(self) -> t.Generator[path.LineagePath]:
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

    def print_json(self) -> None:
        """
        Print the graph as JSON.
        """
        nodes = self.get_nodes()
        edges = self.get_edges()
        queries = self.get_original_queries()
        paths = self.get_paths()

        _nodes = [n.to_dict() for n in nodes]
        _edges = [e.to_dict() for e in edges]
        _queries = [q.to_dict() for q in queries]
        _paths = [p.to_dict() for p in paths]

        print(
            json.dumps(
                {
                    "node": _nodes,
                    "edges": _edges,
                    "queries": _queries,
                    "paths": _paths,
                },
                indent=2,
            )
        )

    def print_tree(self, full_name: bool = False) -> None:
        """
        Print from the leaves to the root (as left to right) so that the tree is displayed correctly.
        Mimics the `tree` utility on Linux.

        For example, given query:
            INSERT INTO fruit.processed
            SELECT SUBSTRING(name, 2, 4) AS name
            FROM fruit.raw

        Output:
            .
            └── column[fruit.processed.name]
                └── function[SUBSTRING]
                    ├── column[fruit.raw.name]
                    ├── literal[2]
                    └── literal[4]
        """
        g = self.graph.reverse(copy=False)  # We print from the leaves to the roots
        attr = "full_name" if full_name else "friendly_name"

        def print_entry(name: str, prefix: str, is_last: bool, ancestors: frozenset[str]) -> None:
            connector = "└── " if is_last else "├── "
            print(prefix + connector + getattr(g.nodes[name]["attrs"], attr))
            # A last entry has no siblings below it, so its children are indented instead of guided
            child_prefix = prefix + ("    " if is_last else "│   ")
            print_children(name, child_prefix, ancestors | {name})

        def print_children(name: str, prefix: str, ancestors: frozenset[str]) -> None:
            children = sorted(n for n in g.successors(name) if n != name and n not in ancestors)
            for i, child in enumerate(children):
                print_entry(child, prefix, i == len(children) - 1, ancestors)

        root_columns = path.get_root_nodes(g)
        print(".")
        for i, root in enumerate(root_columns):
            print_entry(root, "", i == len(root_columns) - 1, frozenset())

    def print_paths(self) -> None:
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

    def register_hooks(self, hooks: list[Hook]) -> None:
        """
        Register user-defined hooks.

        A hook allows a user to provide their own logic to control how nodes are created.
        Each hook is represented by a Hook object which specifies:
        - name: a unique identifier for the hook
        - kind: the Node class the hook applies to
        - func: a callable that accepts a Node instance and returns the Node to use, or None to skip it

        A hook runs after a node has been created, but before the node is added to the graph.
        This gives the user maximum control over the node's properties, exposing attributes
        such as the object's name and its underlying SQL expression for inspection.

        When we attempt to create the path [A -> B -> C] in the graph, if we have a hook that
        prevents the creation of B, then we set A is the previous node, and C as the next,
        resulting in the path [A -> C].

        Examples:
            ### 1. Never create a FunctionNode.
            hooks = [Hook(name="skip_all_functions", kind=FunctionNode, func=lambda n: None)]

            ### 2. Only create a FunctionNode if its name is 'SUM'.
            def my_func(node):
                return node if node.name == "SUM" else None
            hooks = [Hook(name="only_sum", kind=FunctionNode, func=my_func)]
        """
        self.user_defined_hooks.extend(hooks)

    def deregister_hooks(self, hooks: list[Hook]) -> None:
        """
        The inverse of `register_hooks()`: remove a hook (by name) from the list of user-defined hooks.
        """
        self.user_defined_hooks = [udh for udh in self.user_defined_hooks if udh not in hooks]

    def init_object_mapping(self, dialect: str) -> None:
        if not self.object_mapping:
            self.object_mapping = mappings.ObjectMapping(
                dialect=dialect, object_loader=collector.SystemObjectLoader(dialect)
            )


def new_graph() -> MultiDiGraph:
    """
    A graph has attributes along with its node and edges.
    """
    return MultiDiGraph(attrs=GraphAttributes())
