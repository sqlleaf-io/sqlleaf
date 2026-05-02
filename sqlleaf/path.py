from __future__ import annotations
import logging
import typing as t
import networkx as nx

from sqlleaf import util
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes

logger = logging.getLogger("sqlleaf")


class LineagePath:
    def __init__(self, root: str, hops: t.List[EdgeAttributes]):
        self.root = root
        self.hops = hops
        self.path_length = len(hops)
        self.path_id = "path:" + util.short_sha256_hash(":".join(self.get_edge_ids()))

        for i, edge in enumerate(self.hops):
            edge.path_id = self.path_id
            edge.path_hop = i

    def node_hops(self) -> t.List[NodeAttributes]:
        """
        Return the list of nodes in this path.
        """
        hops = [self.hops[0].parent]
        for hop in self.hops:
            hops.append(hop.child)
        return hops

    def get_edge_ids(self):
        """
        In order to distinguish between multiple edges that are part of the same path,
        we need to create a unique id based off data that differentiates them.
        This is done using the edges' "id" attribute.
        """
        return [edge.id for edge in self.hops]

    def to_dict(self):
        return {
            "id": self.path_id,
            "length": len(self.hops),
            "hops": [edge.id for edge in self.hops],
        }


def calculate_paths(graph: nx.MultiDiGraph) -> t.Dict[str, LineagePath]:
    """
    Find all the unique paths in the graph and give each path a unique ID according to the set of edges it contains.

    This only makes sense if multiple procedures / multiple graphs need to be merged. This is because the root of a path
    in a graph may change whenever a new graph is merged. TODO: is this true? remove?

    An edge may belong to multiple paths. This usually indicates a conflict in the ETL processes (e.g. a table's column
    with two sources of INSERTs) but it may still be valid in certain cases (such as re-using a table in different stored procedures)
    so we permit it.
    """
    all_lineage_paths = {}
    root_columns = util.get_root_nodes(graph)

    for i, root in enumerate(root_columns):
        for path in util.find_edge_paths(graph, root):
            if not path:
                continue

            logger.debug("Found edge path: %s --- %s", [e.id for e in path], [(e.parent.friendly_name, e.child.friendly_name) for e in path])
            lineage_path = LineagePath(root=root, hops=path)
            all_lineage_paths[lineage_path.path_id] = lineage_path

    return all_lineage_paths
