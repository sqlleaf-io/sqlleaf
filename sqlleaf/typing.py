import typing as t
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


class TargetObjectType(StrEnum):
    """
    The types of objects that represent a 'target' in an SQL statement.
    """

    FILE = auto()
    PROGRAM = auto()
    STAGE = auto()
    STREAM = auto()
    TABLE = auto()
