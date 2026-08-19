import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test_multi_table_update(holder):
    sql = """
    CREATE TABLE t1 (id INT, val INT);
    CREATE TABLE t2 (id INT, val INT);
    UPDATE t1, t2
    SET t1.val = t2.val, t1.id = 4
    WHERE t1.id = t2.id;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[4]", "column[t1.id]"], ["column[t2.val]", "column[t1.val]"]]


def test_multi_table_update_join(holder):
    sql = """
    CREATE TABLE t1 (id INT, val INT);
    CREATE TABLE t2 (id INT, val INT);
    UPDATE t1 JOIN t2 ON t1.id = t2.id SET t1.val = t2.val;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[t2.val]", "column[t1.val]"]]
