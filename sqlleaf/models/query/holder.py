from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from sqlleaf.models.query import Q
    from sqlleaf.models.query.base import Query


class QueryHolder:
    """
    A container that holds up to three versions of the same SQL statement
    as three distinct Query instances.

    - original:           The parsed, unmodified Query.
    - transformed:        The Query after transformer.py has processed it.
    - downstream_holders: The containers for downstream queries. Used both for structural
                          children (MERGE branches, INSERT ON CONFLICT, UDF bodies) and for
                          call-site substituted queries (CallQuery, ExecuteQuery, UDF call sites).
                          Populated entirely during the Collector phase.
    """

    def __init__(self, original: Query):
        self.original: Query = original
        self.transformed: Query | None = None
        self.downstream_holders: t.List[QueryHolder] = []
        self.parent_holder: QueryHolder | None = None

        self.original.set_holder(self)

    def add_downstream_holder(self, holder: QueryHolder) -> None:
        holder.parent_holder = self
        self.downstream_holders.append(holder)

    def get_all_holders(self, types: t.Tuple | None = None) -> t.List[QueryHolder]:
        """
        Recursively collect all holders (self + children).
        Optionally filter by the type of their `original` query.
        """
        holders = [self]
        for child in self.downstream_holders:
            holders.extend(child.get_all_holders(types))
        if types:
            holders = [h for h in holders if isinstance(h.original, types)]
        return holders

    def set_transformed_query(self, query: Q) -> None:
        self.transformed = query
        self.transformed.set_holder(self)

