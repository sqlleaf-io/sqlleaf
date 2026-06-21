from __future__ import annotations

import typing as t

from sqlleaf.models.query.base import Query


class QueryHolder:
    """
    A container that holds up to three versions of the same SQL statement
    as three distinct Query instances.

    - original:    The collected, unmodified Query.
    - transformed: The Query after transformer.py has processed it.
    - substituted: The Query after UDF substitution (future use).
    """

    def __init__(self, original: Query):
        self.original: Query = original
        self.transformed: Query | None = None
        self.substituted: Query | None = None
        self.child_holders: t.List[QueryHolder] = []
        self.parent_holder: QueryHolder | None = None

    def add_child_holder(self, child_holder: QueryHolder) -> None:
        child_holder.parent_holder = self
        self.child_holders.append(child_holder)

    def get_all_holders(
        self, types: t.Tuple | None = None
    ) -> t.List[QueryHolder]:
        """
        Recursively collect all holders (self + children).
        Optionally filter by the type of their `original` query.
        """
        holders = [self]
        for child in self.child_holders:
            holders.extend(child.get_all_holders(types))
        if types:
            holders = [h for h in holders if isinstance(h.original, types)]
        return holders

    @property
    def active(self) -> Query:
        """
        Return the most-processed available query version.
        Useful for code that just needs *a* valid query.
        """
        return self.transformed or self.original
