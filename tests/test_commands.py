import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlglot

from tests.new_fixtures import holder, is_subset, DIALECT
from sqlleaf.exception import SqlLeafException
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = "postgres"


# sqlglot doesn't support PREPARE/EXECUTE - Falling back to parsing as a 'Command'.
def test__prepare_fails(holder):
    queries = """
    PREPARE my_plan (int) AS SELECT name FROM fruit.raw WHERE age = $1;
    EXECUTE my_plan(101);
    """
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()

    assert len(queries) == 0


# sqlglot doesn't support DO - Falling back to parsing as a 'Command'.
def test__do_fails(holder):
    queries = """
    DO $$
        SELECT 'hello';
    $$ LANGUAGE SQL;
    """
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()

    assert len(queries) == 0


# sqlglot doesn't support CREATE RULE - Falling back to parsing as a 'Command'.
def test__rule(holder):
    queries = """
    CREATE RULE "_RETURN" AS
    ON SELECT TO t1
    DO INSTEAD
        SELECT * FROM t2;
    """
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()

    assert len(queries) == 0
