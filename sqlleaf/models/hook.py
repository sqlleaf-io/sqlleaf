import typing as t

from sqlleaf.models.node import N

class Hook:
    def __init__(self, name: str, kind: N, func: t.Callable[[N], N | None]):
        self.name = name
        self.kind = kind
        self.func = func
