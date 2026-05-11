import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlglot

from tests.new_fixtures import holder
from sqlleaf.objects.query_types import InsertQuery

DIALECT = "postgres"


cases = [
    "INSERT INTO fruit.raw VALUES ('yellow', UPPER('banana'));",
    "INSERT INTO fruit.raw (name, kind) VALUES ('yellow', UPPER('banana'));",
    "INSERT INTO fruit.raw (kind, name) VALUES (UPPER('banana'), 'yellow');",
    "INSERT INTO fruit.raw SELECT 'yellow' as name, UPPER('banana') AS kind;",
    "INSERT INTO fruit.raw SELECT 'yellow', UPPER('banana');",
]


@pytest.mark.parametrize("case", cases)
def test__insert_values(holder, case):
    h = holder(sql=case, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER()]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == list(map(type, h.queries))


def test__insert_values_multiple(holder):
    sql = """
    INSERT INTO fruit.raw (name, kind)
    VALUES ('apple', UPPER('upper_apple')), ('orange', UPPER('upper_orange'));
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["apple"]', 'column[fruit.raw.name]'],
        ['literal["orange"]', 'column[fruit.raw.name]'],
        ['literal["upper_apple"]', 'function[UPPER()]', 'column[fruit.raw.kind]'],
        ['literal["upper_orange"]', 'function[UPPER()]', 'column[fruit.raw.kind]']
    ]
    assert [InsertQuery] == list(map(type, h.queries))
    assert len(h.nodes) == 8
    assert len(h.edges) == 6

def test__insert_default_values(holder):
    sql = """
    CREATE TABLE fruit.a (
        name VARCHAR,
        kind VARCHAR,
        size INT DEFAULT 99
    );
    CREATE TABLE fruit.b (
        color VARCHAR,
        age INT DEFAULT -1
    );
    INSERT INTO fruit.b DEFAULT VALUES;
    INSERT INTO fruit.a VALUES (DEFAULT, NULL, DEFAULT);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["null[NULL]", "column[fruit.b.color]"],
        ["literal[-1]", "column[fruit.b.age]"],
        ["literal[-1]", "column[fruit.b.age]"],
        ["null[NULL]", "column[fruit.a.name]"],
        ["null[NULL]", "column[fruit.a.kind]"],
        ["literal[99]", "column[fruit.a.size]"],
        ["literal[99]", "column[fruit.a.size]"],
    ]
    assert h.queries[2].statement_transformed.sql() == "INSERT INTO fruit.b (color, age) SELECT NULL AS color, -1 AS age"
    assert len(h.nodes) == 12
    assert len(h.edges) == 7


def test__insert_on_conflict_with_table(holder):
    sql = """
    INSERT INTO fruit.processed (name, kind)
    SELECT name, 'apple' as kind
    FROM fruit.raw AS r
    ON CONFLICT (name)
    DO UPDATE SET
        kind = EXCLUDED.kind || r.kind;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ['literal["apple"]', "column[fruit.processed.kind]"],
        ['literal["apple"]', "function[DPIPE()]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.kind]", "function[DPIPE()]", "column[fruit.processed.kind]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__insert_on_conflict_with_values(holder):
    sql = """
    INSERT INTO fruit.processed (name, created_at)
    VALUES ('pear', CURRENT_TIMESTAMP)
    ON CONFLICT (name)
    DO UPDATE SET
        created_at = EXCLUDED.created_at,
        name = LOWER(EXCLUDED.name),
        kind = EXCLUDED.kind;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["pear"]', "column[fruit.processed.name]"],
        ["function[CURRENTTIMESTAMP()]", "column[fruit.processed.created_at]"],
        ['literal["pear"]', "function[LOWER()]", "column[fruit.processed.name]"],
        ["function[CURRENTTIMESTAMP()]", "column[fruit.processed.created_at]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__insert_on_conflict_do_nothing(holder):
    sql = """
    INSERT INTO fruit.processed (name)
    SELECT 'john' AS name
    ON CONFLICT (name)
    DO NOTHING;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [['literal["john"]', 'column[fruit.processed.name]']]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


# Not supported by sqlglot: exception - unexpected token 'OVERRIDING'
def test__insert_overriding(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        INSERT INTO products (id, name) OVERRIDING SYSTEM VALUE VALUES (500, 'Legacy Item');
        """
        h = holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")
