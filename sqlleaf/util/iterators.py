import typing as t

import sqlglot
from sqlglot import exp

from sqlleaf import exception


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


SUPPORTED_LANGUAGES = [
    "SQL",
    "PLPGSQL",
]

def iter_inner_statements(stmt: exp.Expr, dialect: str, wrap: bool = False, language: str = "SQL") -> t.List[exp.Expr]:
    """
    Iterate over the inner statements of a given expression.
    """
    lang = language.upper()
    if language.upper() not in SUPPORTED_LANGUAGES:
        exception.raise_error(exception.UnsupportedFeatureError, message=f"Unsupported language for procedure/function: {lang}")

    if dialect == "postgres" and lang == "PLPGSQL":
        dialect = language

    if isinstance(stmt, (exp.Literal, exp.Heredoc)):
        body_text = stmt.this.strip()
        return sqlglot.parse(body_text, dialect=dialect)
    if isinstance(stmt, exp.Block):
        return stmt.expressions
    if isinstance(stmt, exp.Return):
        return [exp.select(stmt.this)]

    if wrap:
        return [exp.select(stmt)]
    return [stmt]
