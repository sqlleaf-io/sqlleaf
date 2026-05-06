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


def find_all_paths(graph: nx.MultiDiGraph) -> t.Generator[LineagePath]:
    """
    Find all the unique paths in the graph and give each path a unique ID according to the set of edges it contains.

    This only makes sense if multiple procedures / multiple graphs need to be merged. This is because the root of a path
    in a graph may change whenever a new graph is merged. TODO: is this true? remove?

    An edge may belong to multiple paths. This usually indicates a conflict in the ETL processes (e.g. a table's column
    with two sources of INSERTs) but it may still be valid in certain cases (such as re-using a table in different stored procedures)
    so we permit it.
    """
    root_columns = util.get_root_nodes(graph)

    for i, root in enumerate(root_columns):
        for path in find_edge_paths(graph, root):
            if not path:
                continue

            logger.debug("Found edge path: %s --- %s", [e.id for e in path], [(e.parent.friendly_name, e.child.friendly_name) for e in path])
            lineage_path = LineagePath(root=root, hops=path)
            yield lineage_path


def find_edge_paths(g: nx.MultiDiGraph, node: str, path: t.List = None, seen: t.Set = None):
    """
    Find all the complete paths in a graph by traversing the descendants of a node until we find
    a node without any descendants.

    This is the same as the regular find_paths(), but we iterate over all the edges between any two nodes
    so that we include all paths.

    For example, given the graph:
        A -> B -> C -> D

    If there are two edges between A->B and two edges between C->D:
           __         __
          /  \       /  \
     --> A    B --> C    D -->
          \__/       \__/

    then traversing all the edges gives:
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D

    Thus we consider each path during traversal, as each likely has slightly different attributes.

    Returns:
        [(A, B, edge_data={x}), (A, B, edge_data={y}), (B, C, edge_data={z}), ...]
    """
    if path is None:
        path = []
    if seen is None:
        seen = {node}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, node, 1)
    if not desc:
        if not path:
            # Must be a selfloop
            yield from _get_edges_and_find_edge_paths(g, node, node, path, seen)
        else:
            yield path
    else:
        desc = sorted(desc)  # nx.desc() above is non-deterministic
        for n in desc:
            if n in seen:
                yield path
            else:
                yield from _get_edges_and_find_edge_paths(g, node, n, path, seen)


def _get_edges_and_find_edge_paths(g: nx.MultiDiGraph, node_src: str, node_dst: str, path: t.List = None, seen: t.Set = None):
    """
    Get the list of edges between two nodes, and find the paths for each of them.
    """
    edges = g.get_edge_data(node_src, node_dst)
    for idx, data in edges.items():
        hop = data["attrs"]
        yield from find_edge_paths(g, node_dst, path + [hop], seen.union([node_dst]))
