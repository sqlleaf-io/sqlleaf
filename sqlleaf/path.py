from __future__ import annotations

import logging
import typing as t

import networkx as nx

from sqlleaf import exception, util
from sqlleaf.models.node import EdgeAttributes, N

logger = logging.getLogger("sqlleaf")


class LineagePath:
    def __init__(self, hops: t.List[EdgeAttributes]):
        self.hops = hops
        self.length = len(hops)

    @property
    def id(self) -> str:
        return "path:" + util.short_sha256_hash(":".join(self.get_edge_ids()))

    def node_hops(self) -> t.List[N]:
        """
        Return the list of nodes on this path.
        """
        hops = [self.hops[0].parent]
        for hop in self.hops:
            hops.append(hop.child)
        return hops

    def get_edge_ids(self) -> list[str]:
        """
        In order to distinguish between multiple edges that are part of the same path,
        we need to create a unique id based off data that differentiates them.
        This is done using the edges' "id" attribute.
        """
        return [edge.id for edge in self.hops]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "length": len(self.hops),
            "hops": [edge.id for edge in self.hops],
        }


def find_all_paths(graph: nx.MultiDiGraph) -> t.Generator[LineagePath]:
    """
    Find all the unique paths in the graph.

    There are two algorithms depending on the graph's structure:
    - one for those containing root node (a Rooted graph)
    - one for those containing only cycles (a Circuit graph)
    """

    # Cycle handling logic.
    #  [x] Stage 1. Error: Throw an error/warning on cycles that include multiple columns.
    #  [ ] Stage 2. Recovery: For every cycle, print it to the console, and then
    #  remove all their edges; then proceed with printing the remainder.
    cycles = []
    cycle_errors = 0

    for cycle, errors in util.get_cycles(graph):
        if errors > 0:
            cycle_errors += errors
        else:
            cycles.append(cycle)

    if cycle_errors:
        raise exception.GraphError(message=f"Found {cycle_errors} errors with cycles in graph. Remove these.")

    cycles = sorted(cycles)  # simple_cycles() underneath is non-deterministic
    root_columns = util.get_root_nodes(graph)

    if root_columns:
        logger.debug(f"Found root columns in graph: {root_columns}")
        for i, root in enumerate(root_columns):
            for path in find_edges_from_root(graph, root):
                if not path:
                    continue

                if path[0].parent.id == path[0].child.id:
                    # Skip selfloops; these are covered in the dedicated loop below
                    continue

                logger.debug(
                    "Found edge path using root: %s --- %s",
                    [e.id for e in path],
                    [(e.parent.friendly_name, e.child.friendly_name) for e in path],
                )
                lineage_path = LineagePath(hops=path)
                yield lineage_path

    # Check for selfloops (e.g. a column that goes through another node, such as a function)
    for cycle in cycles:
        for path in find_edges_along_cycle_path(graph, cycle):
            logger.debug(
                "Found edge path from cycle: %s --- %s",
                [e.id for e in path],
                [(e.parent.friendly_name, e.child.friendly_name) for e in path],
            )
            lineage_path = LineagePath(hops=path)
            yield lineage_path


def find_edges_along_cycle_path(
    g: nx.MultiDiGraph, cycle: t.List[str], path: t.Optional[t.List[EdgeAttributes]] = None
) -> t.Generator[t.List[EdgeAttributes]]:
    """
    Given a cycle, find all the edges along it and return these as the new path.
    A path must be provided so that iteration doesn't deviate into non-cycle paths.
    """
    if path is None:
        path = []

    depth = len(path)
    if depth == len(cycle) - 1:
        yield path
    else:
        node_src = cycle[depth]
        node_dst = cycle[depth + 1]
        edges = g.get_edge_data(node_src, node_dst)
        for idx, data in edges.items():
            hop = data["attrs"]
            yield from find_edges_along_cycle_path(g, cycle, path + [hop])


def find_edges_from_root(
    g: nx.MultiDiGraph, node: str, path: t.Optional[t.List[EdgeAttributes]] = None, seen: t.Optional[t.Set[str]] = None
) -> t.Generator[t.List[EdgeAttributes]]:
    """
    Find all the complete paths in a graph by traversing the descendants of a node until we find
    a node without any descendants.

    This is the same as the regular find_paths(), but we iterate over all the edges between any two node
    so that we include all paths.

    For example, given the graph:
        A -> B -> C -> D

    If there are two edges between A->B and two edges between C->D:
           __         __
          /  \\       /  \
     --> A    B --> C    D -->
          \\__/       \\__/

    then traversing all the edges gives:
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D

    Thus we consider each path during traversal, as each likely has slightly different attributes.
    """
    if path is None:
        path = []
    if seen is None:
        seen = set()

    if node in seen:
        yield path
    else:
        # If there's a loop [.., X, .., X], discard everything outside of the Xs as the path.
        if selfloop_edges := g.get_edge_data(node, node):
            for idx, data in selfloop_edges.items():
                hop = data["attrs"]
                yield [hop]

        # Get direct descendants
        desc = nx.descendants_at_distance(g, node, 1)
        if not desc:
            yield path
        else:
            desc = sorted(desc)  # nx.desc() above is non-deterministic
            for n in desc:
                yield from _traverse_path_along_edges(g, node, n, path, seen)


def _traverse_path_along_edges(
    g: nx.MultiDiGraph, node_src: str, node_dst: str, path: t.Optional[t.List] = None, seen: t.Optional[t.Set] = None
) -> t.Generator[t.List[EdgeAttributes]]:
    """
    Get the list of edges between two node, and find the paths for each of them.
    """
    if path is None:
        path = []
    if seen is None:
        seen = set()

    edges = g.get_edge_data(node_src, node_dst)
    for idx, data in edges.items():
        hop = data["attrs"]
        yield from find_edges_from_root(g, node_dst, path + [hop], seen.union([node_src]))
