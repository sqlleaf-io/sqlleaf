import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__insert_with_cte(holder):
    sql = """
    INSERT INTO fruit.processed (name, age)
    (WITH cte AS (SELECT name, age FROM fruit.raw) SELECT * FROM cte ORDER BY 1 LIMIT 10);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[cte.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[cte.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


def test__exclude(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, kind VARCHAR, age INT);
    CREATE TABLE target (name VARCHAR, kind VARCHAR);

    INSERT INTO target
    SELECT * EXCLUDE age FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.name]", "column[target.name]"], ["column[source.kind]", "column[target.kind]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
