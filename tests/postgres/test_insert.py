import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import sqlglot

from sqlleaf.models.query import InsertQuery

DIALECT = "postgres"



def test__insert_select_with_aliases(holder):
    sql = "INSERT INTO fruit.raw SELECT 'yellow' as name, UPPER('banana') AS kind;"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__insert_select_without_aliases(holder):
    sql = "INSERT INTO fruit.raw SELECT 'yellow', UPPER('banana');"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


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
        ['literal["apple"]', "function[DPIPE]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.kind]", "function[DPIPE]", "column[fruit.processed.kind]"],
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
        ["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"],
        ["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"],
        ['literal["pear"]', "function[LOWER]", "column[fruit.processed.name]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5


def test__insert_on_conflict_do_nothing(holder):
    sql = """
    INSERT INTO fruit.processed (name)
    SELECT 'john' AS name
    ON CONFLICT (name)
    DO NOTHING;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [['literal["john"]', "column[fruit.processed.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


# Not supported by sqlglot: exception - unexpected token 'OVERRIDING'
def test__insert_overriding(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        INSERT INTO products (id, name) OVERRIDING SYSTEM VALUE VALUES (500, 'Legacy Item');
        """
        holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")
