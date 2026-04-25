from __future__ import annotations
import logging
import typing as t

from sqlleaf import util
from sqlleaf.objects.node_types import EdgeAttributes, NodeAttributes

logger = logging.getLogger("sqleaf")


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
