import typing as t

from sqlglot import exp

E = t.TypeVar("E", bound=exp.Expr)

"""
Represents a source and a target object of an SQL query.

For example,
    INSERT INTO <target> SELECT * FROM <source>
    COPY <target> FROM <source>
"""

TargetExprType = exp.Table | exp.Literal | exp.Identifier | exp.Schema
SourceExprType = exp.Table | exp.Literal | exp.Identifier | exp.Select | exp.Values | exp.Schema
