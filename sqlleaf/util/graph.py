import logging
import typing as t

import networkx as nx

from sqlleaf import util

logger = logging.getLogger("sqlleaf")


def find_edges_downward(g: nx.MultiDiGraph, node: str, seen: t.Optional[t.Set[str]] = None, depth: int = 0):
    """
    Traverse the graph, returning any unseen edges.

    Similar to find_edges_from_root(), except we return an unseen edge found at each hop,
    rather than the entire path leading us there.
    """
    if seen is None:
        seen = {node}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, node, 1)

    for n in desc:
        if n not in seen:
            # TODO: this could be a bug similar to the above comment in function
            edges = g.get_edge_data(node, n)
            for idx, data in edges.items():
                hop = data["attrs"]
                # Depth-first search?
                yield depth, hop
                yield from find_edges_downward(g, n, seen.union([n]), depth + 1)


def find_paths(g: nx.MultiDiGraph, start=0, path: t.Optional[t.List[int]] = None, seen: t.Optional[t.Set[int]] = None):
    """
    Find all the complete paths in a graph by traversing the descendants of a node until we find
    a node without any descendants.
    """
    if path is None:
        path = [start]
    if seen is None:
        seen = {start}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, start, 1)
    if not desc:
        yield path
    else:
        for n in desc:
            if n in seen:
                yield path
            else:
                yield from find_paths(g, n, path + [n], seen.union([n]))


def get_root_nodes(graph: nx.MultiDiGraph) -> t.List[str]:
    """
    Get the root node of a graph. A root node has no parents.
    """
    selfloops = []

    def remove_selfloop_edges(n1: str, n2: str, edge_key: int):
        attrs = graph[n1][n2][edge_key]["attrs"]
        if n1 == n2 and attrs:
            if n1 not in selfloops:
                selfloops.append(n1)
            return False
        return True

    # Remove all the selfloop edges so that we can find the root node,
    # and then add them back. (This is due to in/out_degree() inclduing them as edges)
    view = nx.subgraph_view(graph, filter_edge=remove_selfloop_edges)
    roots = [
        n
        for n in view.nodes
        if
        # A root node
        (view.in_degree(n) == 0 and view.out_degree(n) > 0)
        or
        # A selfloop
        (n in selfloops and view.degree(n) == 0)
    ]
    logger.debug(f"Found selfloops: {selfloops}")
    return roots


def get_cycles(graph: nx.MultiDiGraph):
    """
    Find all cycles in a graph.
    """
    errors = 0

    for cycle in nx.simple_cycles(graph):
        columns = [col for col in cycle if col.startswith("column")]

        if len(util.unique(columns)) == 1:
            # A valid cycle. This is a selfloop that passes through another node, e.g. a function.
            first_column = columns[0]
            idx = cycle.index(first_column)
            new_cycle = cycle[idx:] + cycle[:idx] + [first_column]
            logger.debug(f"Found cycle: {new_cycle}")
            cycle = new_cycle
        else:
            if len(columns) == 0:
                logger.error(f"A cycle must contain 1 column node: {cycle}")
                errors = 1
            elif len(util.unique(columns)) > 1:
                logger.error(f"A cycle cannot contain more than 1 column (found {len(util.unique(columns))}): {cycle}")
                errors = 1

        yield cycle, errors
