import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import sqlglot

from sqlleaf.models.query import InsertQuery

DIALECT = "postgres"


def test__insert_with_cte(holder):
    sql = """
    INSERT INTO fruit.processed (name, age)
    (WITH cte AS (SELECT name, age FROM fruit.raw) SELECT * FROM cte ORDER BY 1 LIMIT 10);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[cte.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[cte.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


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

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (name, kind) SELECT r.name AS name, 'apple' AS kind FROM fruit.raw AS r"
    assert h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (kind) SELECT 'apple' || r.kind AS kind FROM fruit.raw AS r"

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
        kind = UPPER(EXCLUDED.kind);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (name, created_at) SELECT 'pear' AS name, CURRENT_TIMESTAMP AS created_at"
    )
    # The inner UPDATE query
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed (created_at, name, kind) "
        "SELECT CURRENT_TIMESTAMP AS created_at, LOWER('pear') AS name, UPPER(processed.kind) AS kind "
        "FROM fruit.processed AS processed"
    )

    assert h.paths == [
        ['literal["pear"]', "column[fruit.processed.name]"],
        ["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"],
        ['literal["pear"]', "function[LOWER]", "column[fruit.processed.name]"],
        ["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"],
        ["column[fruit.processed.kind]", "function[UPPER]", "column[fruit.processed.kind]"],
    ]
    assert len(h.nodes) == 9
    assert len(h.edges) == 7


def test__insert_on_conflict_do_nothing(holder):
    sql = """
    INSERT INTO fruit.processed (name)
    SELECT 'john' AS name
    ON CONFLICT (name)
    DO NOTHING;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (name) SELECT 'john' AS name"

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
    assert (
        h.holders[2].transformed.statement.sql() == "INSERT INTO fruit.b (color, age) SELECT NULL AS color, -1 AS age"
    )
    assert len(h.nodes) == 12
    assert len(h.edges) == 7


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


def test__insert_select_star_with_warn_on_error(holder):
    sql = """
    INSERT INTO fruit.raw SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True, on_error="warn")

    assert h.paths == [
        ["star[*]", "column[fruit.raw.name]"],
    ]
    assert [InsertQuery] == h.query_types
