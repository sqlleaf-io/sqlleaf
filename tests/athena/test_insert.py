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
        "column[name=amount table=processed schema=fruit type=INT kind=table]",
        "column[name=name table=processed schema=fruit type=VARCHAR kind=table]",
        "column[name=amount table=raw schema=fruit type=INT kind=table]",
        "column[name=name table=raw schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2
