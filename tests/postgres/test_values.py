import os
import sys

import pytest
from sqlglot import exp

from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import InsertQuery, ValuesQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def to_sql(expressions: list[exp.Expr]) -> list[str]:
    return [e.sql(dialect=DIALECT) for e in expressions]


def test__values_standalone_single(holder):
    sql = """
    VALUES (1);
    """
    h = holder(sql=sql, dialect=DIALECT)
    query = h.queries_original[0]
    assert isinstance(query, ValuesQuery)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "SELECT 1 AS column1"

    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


def test__values_standalone_multiple(holder):
    sql = """
    VALUES (1), (2);
    """
    h = holder(sql=sql, dialect=DIALECT)
    query = h.queries_original[0]
    assert isinstance(query, ValuesQuery)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT) == "SELECT 1 AS column1 UNION ALL SELECT 2 AS column1"
    )

    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


def test__values_standalone_multiple_two(holder):
    sql = """
    VALUES (1, 1), (2, 3);
    """
    h = holder(sql=sql, dialect=DIALECT)
    query = h.queries_original[0]
    assert isinstance(query, ValuesQuery)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "SELECT 1 AS column1, 1 AS column2 UNION ALL SELECT 2 AS column1, 3 AS column2"
    )

    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


def test__values_parenthesized(holder):
    sql = """
    INSERT INTO fruit.raw (name, kind)
    (VALUES ('yellow', UPPER('banana')));
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.raw (name, kind) SELECT 'yellow' AS name, UPPER('banana') AS kind"
    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_nested_values(holder):
    sql = """
    INSERT INTO fruit.raw
    VALUES ('yellow', (VALUES(UPPER('banana'))));
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


# TODO: print the transformed query for each to ensure correctness
def test__values_multiple(holder):
    sql = """
    INSERT INTO fruit.raw (name, kind)
    VALUES ('apple', UPPER('upper_apple')), ('orange', UPPER('upper_orange'));
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["apple"]', "column[fruit.raw.name]"],
        ['literal["orange"]', "column[fruit.raw.name]"],
        ['literal["upper_apple"]', "function[UPPER]", "column[fruit.raw.kind]"],
        ['literal["upper_orange"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types
    assert len(h.nodes) == 8
    assert len(h.edges) == 6


def test__values_basic(holder):
    sql = "INSERT INTO fruit.raw VALUES ('yellow', UPPER('banana'));"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_with_columns(holder):
    sql = "INSERT INTO fruit.raw (name, kind) VALUES ('yellow', UPPER('banana'));"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_with_reordered_columns(holder):
    sql = "INSERT INTO fruit.raw (kind, name) VALUES (UPPER('banana'), 'yellow');"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_with_alias_no_columns(holder):
    sql = """
    INSERT INTO fruit.raw (name, kind)
    SELECT *
    FROM (VALUES('yellow', UPPER('banana'))) v;
"""
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.raw (name, kind) SELECT v.column1 AS name, v.column2 AS kind FROM (SELECT 'yellow' AS column1, UPPER('banana') AS column2) AS v"
    assert h.paths == [
        ['literal["yellow"]', 'column[v.column1]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", 'column[v.column2]', "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_with_alias_one_column(holder):
    sql = """
    INSERT INTO fruit.raw (name, kind)
    SELECT *
    FROM (VALUES('yellow', UPPER('banana'))) v(column1);
"""
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.raw (name, kind) SELECT v.column1 AS name, v.column2 AS kind FROM (SELECT 'yellow' AS column1, UPPER('banana') AS column2) AS v"
    assert h.paths == [
        ['literal["yellow"]', 'column[v.column1]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", 'column[v.column2]', "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__values_with_alias_one_column_fails(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        INSERT INTO fruit.raw (name, kind)
        SELECT *
        FROM (VALUES('yellow', UPPER('banana'))) v(column2);
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0] == "Column reference 'v.column2' is ambiguous (2 possible options)"
