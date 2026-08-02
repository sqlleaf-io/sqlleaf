import typing as t
from functools import cache

from sqlglot import exp

from sqlleaf.settings.base import BaseDialectSettings
from sqlleaf.settings.postgres import PostgresSettings
from sqlleaf.settings.athena import AthenaSettings


@cache
def system_columns(dialect: str)-> t.List[exp.ColumnDef]:
    return BaseDialectSettings.from_dialect(dialect).system_columns

@cache
def system_functions(dialect: str) -> t.Dict[str, t.List[str]]:
    # TODO: refactor this into a set of objects that can be loaded into the mapping
    return BaseDialectSettings.from_dialect(dialect).system_functions
