import typing as t
from functools import cache

from sqlglot import exp
from sqlglot.dialects import postgres


@cache
def system_columns(dialect: str)-> t.List[exp.ColumnDef]:
    return DialectSettings.from_dialect(dialect).system_columns


class DialectSettings:
    # A registry to store subclasses
    _dialects = {}
    DIALECT = ""

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        if cls.DIALECT:
            DialectSettings._dialects[cls.DIALECT] = cls

    @classmethod
    def from_dialect(cls, dialect: str) -> DialectSettings:
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(dialect)
        if not target_class:
            return DialectSettings()
        return target_class()

    @property
    def system_columns(self) -> t.List[exp.ColumnDef]:
        """
        Create a set of ColumnDefs representing system columns for a given dialect.
        """
        return []


class PostgresSettings(DialectSettings):
    DIALECT = "postgres"
    PSEUDOCOLUMNS = {
        "cmax": "OID",
        "cmin": "OID",
        "ctid": "OID",
        "oid": "OID",
        "tableoid": "OID",
        "xmax": "OID",
        "xmin": "OID",
    }

    @property
    def system_columns(self) -> t.List[exp.ColumnDef]:
        return [exp.ColumnDef(
            this=exp.to_identifier(name),
            kind=exp.DataType.build(kind, self.DIALECT)
        ) for name, kind in self.PSEUDOCOLUMNS.items()]


# sqlglot is missing pseudocolumns for Postgres
postgres.Postgres.PSEUDOCOLUMNS = {c.upper() for c in PostgresSettings.PSEUDOCOLUMNS.keys()}
postgres.Postgres.EXCLUDES_PSEUDOCOLUMNS_FROM_STAR = True
