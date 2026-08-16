import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import TableQuery, UpdateQuery

DIALECT = ""


def test__update_simple(holder):
    sql = """
    UPDATE fruit.processed p
    SET name = 'john', age = r.age
    FROM fruit.raw r;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["john"]', "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
    ]
    assert [UpdateQuery] == h.query_types
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__update_with_subquery(holder):
    sql = """
    UPDATE fruit.processed
    SET amount = (
        SELECT COUNT(kind)
        FROM fruit.raw
    ), age = 5;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[5]", "column[fruit.processed.age]"],
        ["column[fruit.raw.kind]", "function[COUNT]", "column[fruit.processed.amount]"],
    ]
    assert len(h.nodes_full) == 5
    assert len(h.edges) == 3
    assert [UpdateQuery] == h.query_types


def test__update_with_join(holder):
    sql = """
    UPDATE fruit.processed p
    SET age = r.age
    FROM fruit.raw r
    WHERE p.name = r.name;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.age]", "column[fruit.processed.age]"]]
    assert len(h.nodes_full) == 2
    assert len(h.edges) == 1
    assert [UpdateQuery] == h.query_types


def test__update_with_multiple_joins(holder):
    sql = """
    CREATE TABLE fruit.old (name VARCHAR);

    UPDATE fruit.processed p
    SET age = r.age
    FROM fruit.raw r
    JOIN fruit.old o
    ON r.name = o.name
    WHERE p.name = r.name;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.age]", "column[fruit.processed.age]"]]
    assert len(h.nodes_full) == 2
    assert len(h.edges) == 1
    assert [TableQuery, UpdateQuery] == h.query_types


def test__update_with_case(holder):
    sql = """
    UPDATE fruit.processed
    SET name = CASE
        WHEN age > 50 THEN 'old'
        ELSE 'young'
    END;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["young"]', "column[fruit.processed.name]"],
        ['literal["old"]', "column[fruit.processed.name]"],
    ]
    assert len(h.nodes_full) == 3
    assert len(h.edges) == 2
    assert [UpdateQuery] == h.query_types


def test__update_with_function(holder):
    sql = """
    UPDATE fruit.processed
    SET name = LOWER(name);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.name]", "function[LOWER]", "column[fruit.processed.name]"],
    ]
    assert len(h.nodes_full) == 2
    assert len(h.edges) == 2
    assert [UpdateQuery] == h.query_types


def test__update_with_subquery_in_from(holder):
    sql = """
    UPDATE fruit.processed p
    SET age = s.max_age
    FROM (
        SELECT MAX(age) as max_age, kind
        FROM fruit.raw
        GROUP BY kind
    ) s
    WHERE p.kind = s.kind;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.age]", "function[MAX]", "column[s.max_age]", "column[fruit.processed.age]"]]
    assert [UpdateQuery] == h.query_types



def test__update_multiple_columns(holder):
    sql = """
    UPDATE fruit.processed
    SET (name, age) = ('apple', 10);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["apple"]', "column[fruit.processed.name]"],
        ["literal[10]", "column[fruit.processed.age]"],
    ]
    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed (name, age) SELECT 'apple' AS name, 10 AS age FROM fruit.processed AS processed"
    )


def test__update_multiple_columns_from_select(holder):
    sql = """
    UPDATE fruit.processed
    SET (name, age) = (SELECT UPPER(name), age FROM fruit.raw WHERE id = 1);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "function[UPPER]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
    ]
    assert h.nodes_full == [
        "function[name=UPPER type=VARCHAR position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=age type=INT properties=[kind=table table=raw schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]

    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed (name, age) SELECT UPPER(raw.name) AS name, raw.age AS age FROM fruit.raw AS raw"
    )


def test__update_single_column_tuple(holder):
    sql = "UPDATE fruit.raw SET (name) = (SELECT 'foo')"

    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.raw (name) SELECT 'foo' AS name FROM fruit.raw AS raw"
    )

    assert h.paths == [['literal["foo"]', "column[fruit.raw.name]"]]
    assert h.nodes_full == [
        'literal[name="foo" type=VARCHAR position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
