import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__prepare(holder):
    sql = """
    PREPARE stmt1 FROM
    'SELECT SQRT(POW(?,2) + POW(?,2)) AS hypotenuse';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.lineage.collected_queries.unsupported) == 1
    assert h.paths == []


def test__execute(holder):
    sql = """
    PREPARE my_select3 FROM
    SELECT order FROM orders WHERE productid = ? and quantity < ?;

    EXECUTE my_select3 USING 346078, 12;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 2
    assert h.paths == []
