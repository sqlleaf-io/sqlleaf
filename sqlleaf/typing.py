import typing as t
from dataclasses import dataclass
from enum import StrEnum, auto

from sqlglot import exp
from sqlglot.optimizer import Scope

E = t.TypeVar("E", bound=exp.Expr)

"""
Represents a source and a target object of an SQL query.

For example,
    INSERT INTO <target> SELECT * FROM <source>
    COPY <target> FROM <source>
"""

TargetExprType = exp.Table | exp.Literal | exp.Identifier | exp.Schema
SourceExprType = exp.Table | exp.Literal | exp.Identifier | exp.Select | exp.Schema | exp.Values

TableOrScopeType = exp.Table | Scope


class SqlObjectType(StrEnum):
    """
    The types of models that represent a 'source' or 'target' in an SQL statement.
    """

    NONE = auto()

    # Targets and sources
    DATABASE = auto()
    DYNAMODB = auto()
    FILE = auto()
    PREPARED_STATEMENT = auto()
    PROCEDURE = auto()
    PROGRAM = auto()
    SCHEMA = auto()
    STAGE = auto()
    STREAM = auto()
    TABLE = auto()
    # Sources
    DML = auto()
    SELECT = auto()
    SET = auto()  # Temporary
    TUPLE = auto()  # Temporary
    VALUES = auto()

    @classmethod
    def type_has_no_column_defs(cls, *clses: t.Iterable) -> bool:
        """
        Return all the types that do not define any columns of their own.
        """
        return not set(clses).isdisjoint({
            cls.DYNAMODB,
            cls.FILE,
            cls.PROGRAM,
            cls.STAGE,
            cls.STREAM,
            cls.PROCEDURE,
            cls.PREPARED_STATEMENT,
        })


@dataclass(frozen=True)
class SourceInfo:
    expression: SourceExprType
    type: SqlObjectType


@dataclass(frozen=True)
class TargetInfo:
    expression: TargetExprType
    type: SqlObjectType


# TODO: merge this with SqlObjectType?
class TableType(StrEnum):
    TABLE = auto()
    VIEW = auto()
    CTE = auto()
    DERIVED_TABLE = auto()
    STAGE = auto()
    FILE = auto()
    UDTF = auto()  # LATERAL hello() as hello(col1, col2)
    PROCEDURE = auto()


class TableSubtype(StrEnum):
    RECURSIVE = auto()
    TEMPORARY = auto()
    EXTERNAL = auto()
    MATERIALIZED = auto()
