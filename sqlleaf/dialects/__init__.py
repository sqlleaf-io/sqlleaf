from sqlleaf.dialects.plpgsql.p_dialect import PlPgSQL

from functools import cache

from sqlglot import exp

from sqlleaf.dialects.athena.config import AthenaSettings as AthenaSettings
from sqlleaf.dialects.base import BaseDialectSettings as BaseDialectSettings
from sqlleaf.dialects.postgres.config import PostgresSettings as PostgresSettings


@cache
def system_columns(dialect: str) -> list[exp.ColumnDef]:
    return BaseDialectSettings.from_dialect(dialect).system_columns


@cache
def system_functions(dialect: str) -> dict[str, list[str]]:
    # TODO: refactor this into a set of objects that can be loaded into the mapping
    return BaseDialectSettings.from_dialect(dialect).system_functions
