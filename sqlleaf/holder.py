import logging
import json
import typing as t
import networkx as nx

from sqlleaf import mappings, util, structs, lineage, query_builder

logger = logging.getLogger("sqleaf")


class Lineage:
    """
    Holds the lineage as a networkx graph.
    """

    def __init__(self):
        self.graph = structs.new_graph()  # The graph that contains all lineage
        self.subgraphs: t.List[nx.MultiDiGraph] = []  # The subgraphs that make up the main graph
        self.paths: t.Dict[str, t.List[structs.EdgeAttributes]] = {}  # The paths throughout the graph
        self.object_mapping = None

    def generate(self, sql: str, dialect: str):
        if not self.object_mapping:
            self.object_mapping = mappings.ObjectMapping(dialect=dialect)

        queries = query_builder.collect_queries(sql, dialect, self.object_mapping)

        for query in queries:
            if query.has_statement:  # Queries without DML statements (e.g. CREATE TABLE) have no lineage
                query = lineage.transform_query(query, self.object_mapping)
                graph = lineage.get_lineage_for_query(query, self.object_mapping)
                lineage.update_column_data_types(self.graph)
                self.merge_graph(graph)

            self.graph.graph["attrs"].add_query(query)

        self.paths = lineage.calculate_paths(graph=self.graph)

    def merge_graph(self, new_graph: nx.MultiDiGraph):
        """
        Merge the subgraph into the main graph, and also track the individual subgraphs.
        """
        self.subgraphs.append(new_graph)

        for n, data in new_graph.nodes(data=True):
            if self.graph.has_node(n):
                old_node_attrs = self.graph.nodes[n]['attrs']

                # The incoming graph's edges must have their NodeAttributes updated to match the existing graph's NodeAttributes.
                # This is because different graphs with identical Nodes will have different NodeAttributes Python objects.
                for par, chi, edge_data in new_graph.edges(data=True):
                    # Overwrite the new edge's Node to be the old Node
                    if edge_data["attrs"].parent.full_name == n:
                        edge_data["attrs"].parent = old_node_attrs
                    if edge_data["attrs"].child.full_name == n:
                        edge_data["attrs"].child = old_node_attrs
            else:
                self.graph.add_node(n, **data)

        self.graph.add_edges_from(new_graph.edges(data=True))

    def get_edges(self) -> t.List[structs.EdgeAttributes]:
        edges = [data["attrs"] for par, chi, data in self.graph.edges(data=True)]
        edges = sorted(edges, key=lambda e: (e.select_idx, e.path_idx))
        return edges

    def get_nodes(self) -> t.List[structs.NodeAttributes]:
        nodes = [data["attrs"] for n, data in self.graph.nodes(data=True)]
        # TODO: sort on full_name?
        nodes = sorted(nodes, key=lambda e: (e.catalog, e.schema, e.table, e.column))
        return nodes

    def get_queries(self) -> t.List[structs.Query]:
        """
        Get the queries from each of the subgraphs.
        """
        return self.graph.graph["attrs"].queries

    def get_stored_procedures(self):
        """
        Get the stored procedures from each of the edges.
        """
        return []

    def get_paths(self) -> t.List:
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
        return list(self.paths.values())

    def print_json(self) -> t.Dict:
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


        print(json.dumps({
            "nodes": _nodes,
            "edges": _edges,
            "queries": _queries,
            "stored_procedures": _sps,
            "paths": _paths,
        }, indent=2))

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
        root_columns = lineage._get_root_nodes(g)
        seen = set()

        attr = "full_name" if full_name else "friendly_name"

        # TODO: this may not be needed since the NodeAttributes are nodes
        for i, root in enumerate(root_columns):
            for depth, edge_attrs in util.find_edges_downward(g, root):  # TODO: fetch edges in order of function argument index
                # Swap the parent and child
                parent_name = edge_attrs.child.full_name
                child_name = edge_attrs.parent.full_name
                num_descendents_of_child = len(nx.descendants(g, child_name))

                parent_node = g.nodes[parent_name]['attrs']
                child_node = g.nodes[child_name]['attrs']

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
                        prefix = ((depth) * 4 * " ") + f"{symbol} "
                    print("%s%s" % (prefix, getattr(child_node, attr)))
                    seen.add(child_name)

    def to_paths(self):
        """
        Iterate over all the paths in the graph and format them as a friendly, human-readable set of strings.

        Example:
          sqlleaf lineage --functions='*'

        Output:
          column=[fruit.raw.apple],functions=[SUBSTR,UPPER]  ->  column=[fruit.processed.apple]
          functions=[count(*)]   ->  column=[fruit.processed.amount]
        """
        return ""
