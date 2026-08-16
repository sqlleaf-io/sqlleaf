import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import InsertQuery, UpdateQuery

DIALECT = ""


def test__merge_only_update(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
    ]
    assert len(h.nodes) == 2
    assert len(h.queries_original) == 1
    assert [UpdateQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (name) SELECT s.name AS name FROM fruit.raw AS s"
    )


def test__merge_only_insert(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
    ]
    assert len(h.nodes) == 2
    assert len(h.queries_original) == 1
    assert [InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )


def test__merge_with_function(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = LOWER(s.name);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "function[LOWER]", "column[fruit.processed.name]"],
    ]
    assert len(h.nodes) == 3
    assert len(h.queries_original) == 1
    assert [UpdateQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (name) SELECT LOWER(s.name) AS name FROM fruit.raw AS s"
    )


def test__merge_two_identical_insert_clauses(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind)
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
    ]
    assert len(h.nodes) == 2
    assert len(h.queries_original) == 1
    assert [InsertQuery, InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )
    assert (
        h.holders[0].downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )


def test__merge_with_values_in_insert(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN NOT MATCHED THEN
        INSERT (label, name) VALUES (s.kind, 'apple');
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        [
            'literal["apple"]',
            "column[fruit.processed.name]",
        ],
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.queries_original) == 1
    assert [InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label, name) SELECT s.kind AS label, 'apple' AS name FROM fruit.raw AS s"
    )


def test__merge_simple_update_and_insert(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.queries_original) == 1
    assert [UpdateQuery, InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert (
        h.holders[0].downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (name) SELECT s.name AS name FROM fruit.raw AS s"
    )
    assert (
        h.holders[0].downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )


def test__merge_using_select(holder):
    sql = """
    MERGE INTO fruit.processed AS t
    USING (SELECT kind, name FROM fruit.raw) AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (kind, label) VALUES (s.kind, s.name);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.label]"],
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.kind]", "column[fruit.processed.kind]"],
    ]


# TODO: test two merge queries that have an identical inner query
#  expect: the two inner queries are identical (and preserved), but they have different parents
