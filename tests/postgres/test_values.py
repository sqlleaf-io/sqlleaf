import os
import sys

from sqlleaf.models.query import ValuesQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__values_paren(holder):
    sql = """
    (VALUES (1, 2));
    """
    h = holder(sql=sql, dialect=DIALECT)
    query = h.queries_original[0]
    assert isinstance(query, ValuesQuery)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "SELECT 1 AS column1, 2 AS column2"

    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
