import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__pseudocolumns(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target (name) SELECT "$path" FROM source WHERE "$path" LIKE '%2023-01-01%';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.$path]", "column[target.name]"]]
    assert h.nodes_full == [
        "column[name=$path type=VARCHAR properties=[kind=table table=source]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 1
