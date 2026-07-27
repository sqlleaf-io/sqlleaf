import os
import sys

import pytest
from sqlglot import exp

from sqlleaf.models.query import ValuesQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def to_sql(expressions: list[exp.Expr]) -> list[str]:
    return [e.sql(dialect="postgres") for e in expressions]


def test__values(holder):
    sql = """
    VALUES (1);
    """
    h = holder(sql=sql, dialect=DIALECT)
    query = h.queries_original[0]
    assert isinstance(query, ValuesQuery)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "SELECT 1 AS column1"

    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
