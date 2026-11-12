import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__view(holder):
    sql = """
    CREATE TABLE t1 (name VARCHAR, age INT);
    CREATE ALGORITHM=MERGE VIEW v1 AS SELECT * FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[t1.name]", "column[v1.name]"],
        ["column[t1.age]", "column[v1.age]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
