import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


DIALECT = "postgres"


def test__json_one_selector(holder):
    sql = """
    INSERT INTO fruit.processed
    SELECT jsonblob -> 'fruits' AS name
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        [
            "column[fruit.raw.jsonblob]",
            "jsonpath[.fruits]",
            "column[fruit.processed.name]",
        ]
    ]
    assert h.nodes_full == [
        "jsonpath[.fruits depth=1]",
        "column[name=name table=processed schema=fruit type=VARCHAR kind=table]",
        "column[name=jsonblob table=raw schema=fruit type=JSONB kind=table]",
    ]


def test__json_two_selectors(holder):
    sql = """
    INSERT INTO fruit.processed
    SELECT jsonblob ->> 'fruits' -> 'apple' AS name
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.jsonblob]", "jsonpath[.fruits.apple]", "column[fruit.processed.name]"]]
    assert h.nodes_full == [
        "jsonpath[.fruits.apple depth=2]",
        "column[name=name table=processed schema=fruit type=VARCHAR kind=table]",
        "column[name=jsonblob table=raw schema=fruit type=JSONB kind=table]",
    ]
