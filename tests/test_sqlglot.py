"""
Tests taken from:
https://github.com/tobymao/sqlglot/blob/main/tests/dialects/test_postgres.py
"""

import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import (
    holder
)

DIALECT = 'postgres'

tests = [
"SELECT GET_BIT(CAST(44 AS BIT(10)), 6)",
"SELECT COSH(1.5)",
"SELECT EXP(1)",
"SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name FROM fruit.raw",
"SELECT ARRAY[1, 2, 3]",
"SELECT TRIM(LEADING 'bla' FROM ' XXX ' COLLATE utf8_bin)",
"SELECT name FROM fruit.raw CROSS JOIN LATERAL UNNEST(ARRAY[1])",
# "SELECT * FROM JSON_ARRAY_ELEMENTS('[1,true, [2,false]]') WITH ORDINALITY",  # Fails!
]

@pytest.mark.parametrize("query", tests)
def test_expression(query, holder):
    h = holder(with_tables=True)
    q = "INSERT INTO fruit.processed " + query + " AS name;"
    h.generate(q, dialect=DIALECT)
