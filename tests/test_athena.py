import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import (
    holder,
)

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
        ["column[fruit.raw.amount]", "column[fruit.processed.amount]"]
    ]
    assert h.nodes_full == [
        "column[fruit.processed.amount type=INT kind=table]",
        "column[fruit.processed.name type=VARCHAR kind=table]",
        "column[fruit.raw.amount type=INT kind=table]",
        "column[fruit.raw.name type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2
