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
SourceExprType = exp.Table | exp.Literal | exp.Identifier | exp.Select | exp.Values | exp.Schema

TableOrScopeType = exp.Table | Scope



class SqlObjectType(StrEnum):
    """
    The types of models that represent a 'source' or 'target' in an SQL statement.
    """

    # Targets and sources
    DATABASE = auto()
    FILE = auto()
    PROGRAM = auto()
    SCHEMA = auto()
    STAGE = auto()
    STREAM = auto()
    TABLE = auto()
    # Sources
    SELECT = auto()
    VALUES = auto()
    SET = auto()  # Temporary
    TUPLE = auto()  # Temporary



@dataclass(frozen=True)
class SourceInfo:
    expression: SourceExprType
    type: SqlObjectType


@dataclass(frozen=True)
class TargetInfo:
    expression: TargetExprType
    type: SqlObjectType
    #column_expressions: t.List[exp.Expr]


class TableType(StrEnum):
    TABLE = auto()
    VIEW = auto()
    CTE = auto()
    DERIVED_TABLE = auto()
    STAGE = auto()
    FILE = auto()
    UDTF = auto()   # LATERAL hello() as hello(col1, col2)


class TableSubtype(StrEnum):
    RECURSIVE = auto()
    TEMPORARY = auto()
    EXTERNAL = auto()
    MATERIALIZED = auto()


class IncludeNodesArgs(t.TypedDict, total=False):
    # These are placeholders and currently not implemented.
    include_literals: bool
    include_functions: bool
    include_nulls: bool
    include_vars: bool
    include_variables: bool
    include_ctes: bool
    include_derived_tables: bool
    include_pivots: bool
    include_system_tables: bool
    include_defaults: bool
    include_udfs: bool
    include_stars: bool
    include_sequences: bool
    include_stages: bool
    include_windows: bool
    include_intervals: bool
