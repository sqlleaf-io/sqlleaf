import os
import sys


from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = ""


def test__table_with_default_columns(holder):
    sql = """
    CREATE TABLE fruit (name varchar, size int default 1, age int default 42);

    INSERT INTO fruit
    SELECT 'apple' as name, 10 as size;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["apple"]', "column[fruit.name]"],
        ["literal[1]", "column[fruit.size]"],
        ["literal[10]", "column[fruit.size]"],
        ["literal[42]", "column[fruit.age]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 4


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



def test__update_with_default(holder):
    sql = """
    CREATE TABLE source(age INT DEFAULT 3);

    UPDATE source
    SET age = DEFAULT;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[3]", "column[source.age]"],
        ["literal[3]", "column[source.age]"],
    ]
    assert len(h.nodes_full) == 2
    assert len(h.edges) == 2

