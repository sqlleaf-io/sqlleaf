import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

DIALECT = "postgres"


# sqlglot doesn't support PREPARE/EXECUTE - Falling back to parsing as a 'Command'.
def test__prepare_fails(holder):
    sql = """
    PREPARE my_plan (int) AS SELECT name FROM fruit.raw WHERE age = $1;
    EXECUTE my_plan(101);
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.queries) == 0


# sqlglot doesn't support DO - Falling back to parsing as a 'Command'.
def test__do_fails(holder):
    sql = """
    DO $$
        SELECT 'hello';
    $$ LANGUAGE SQL;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.queries) == 0


# sqlglot doesn't support CREATE RULE - Falling back to parsing as a 'Command'.
def test__rule(holder):
    sql = """
    CREATE RULE "_RETURN" AS
    ON SELECT TO t1
    DO INSTEAD
        SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.queries) == 0
