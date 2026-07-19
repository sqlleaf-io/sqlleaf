import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__example(holder):
    sql = """
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target SELECT 'hello' AS name;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['literal["hello"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
