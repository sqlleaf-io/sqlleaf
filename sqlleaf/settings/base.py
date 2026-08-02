import typing as t
from functools import cache

from sqlglot import exp


class BaseDialectSettings:
    # A registry to store subclasses
    _dialects = {}
    DIALECT = ""

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        if cls.DIALECT:
            BaseDialectSettings._dialects[cls.DIALECT] = cls

    @classmethod
    def from_dialect(cls, dialect: str) -> BaseDialectSettings:
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(dialect)
        if not target_class:
            return BaseDialectSettings()
        return target_class()

    @property
    def system_columns(self) -> t.List[exp.ColumnDef]:
        """
        Represents system columns.
        """
        return []

    @property
    def system_functions(self) -> t.Dict[str, t.List[str]]:
        """
        Represents system functions.
        """
        return {}
