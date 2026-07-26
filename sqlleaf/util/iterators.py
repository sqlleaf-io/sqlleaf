import typing as t

import sqlglot
from sqlglot import exp


def default_column_index_iterator(dialect: str, elems: t.List[t.Any]) -> t.Generator[str]:
    """
    Generates default columns defined for a specific SQL dialect.
    """
    for i in range(len(elems)):
        if dialect == "postgres":
            yield f"column{i + 1}"
        elif dialect == "mysql":
            yield f"column_{i}"
        else:
            yield f"column{i + 1}"


def iter_inner_statements(stmt: exp.Expr, dialect: str, wrap: bool = False) -> t.List[exp.Expr]:
    """
    Iterate over the inner statements of a given expression.
    """
    if isinstance(stmt, (exp.Literal, exp.Heredoc)):
        body_text = stmt.this.strip()
        try:
            return sqlglot.parse(body_text, read=dialect)
        except Exception:
            return []
    if isinstance(stmt, exp.Block):
        return stmt.expressions
    if isinstance(stmt, exp.Return):
        return [exp.select(stmt.this)]

    if wrap:
        return [exp.select(stmt)]
    return [stmt]
