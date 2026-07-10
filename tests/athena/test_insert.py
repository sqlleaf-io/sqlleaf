import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "athena"


def test__insert_into_select(holder):
    sql = """
    CREATE TABLE fruit.raw (name VARCHAR, amount INT);
    CREATE TABLE fruit.processed (name VARCHAR, amount INT);

    INSERT INTO fruit.processed
    SELECT name, amount
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.amount]", "column[fruit.processed.amount]"],
    ]
    assert h.nodes_full == [
        "column[name=amount type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=amount type=INT properties=[kind=table table=raw schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
    assert len(h.edges) == 2
