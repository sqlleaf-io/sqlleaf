import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import TableQuery, UpdateQuery

DIALECT = "postgres"


def test__update_self_join(holder):
    sql = """
    UPDATE fruit.processed t
    SET age = t2.age
    FROM fruit.processed AS t2
    WHERE t.name = t2.name;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.age]", "column[fruit.processed.age]"],
    ]
    assert h.nodes_full == ["column[name=age type=INT properties=[kind=table table=processed schema=fruit]]"]
    assert len(h.edges) == 1
    assert [UpdateQuery] == h.query_types


def test__update_values(holder):
    sql = """
    UPDATE fruit.processed p
    SET (name, age) = (VALUES('apple', 10));
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS p (name, age) SELECT 'apple' AS name, 10 AS age FROM fruit.processed AS p"
    )
    assert h.paths == [
        ['literal["apple"]', "column[fruit.processed.name]"],
        ["literal[10]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes_full) == 4
    assert len(h.edges) == 2


def test__update_from_values(holder):
    sql = """
    UPDATE fruit.processed p
    SET name = v.new_name, age = v.new_age
    FROM (
        VALUES ('apple', 10), ('banana', 20)
    ) AS v(new_name, new_age);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS p (name, age) SELECT v.new_name AS name, v.new_age AS age FROM (SELECT 'apple' AS new_name, 10 AS new_age UNION ALL SELECT 'banana' AS new_name, 20 AS new_age) AS v"
    )

    assert h.paths == [
        ['literal["apple"]', "column[v.new_name]", "column[fruit.processed.name]"],
        ['literal["banana"]', "column[v.new_name]", "column[fruit.processed.name]"],
        ["literal[10]", "column[v.new_age]", "column[fruit.processed.age]"],
        ["literal[20]", "column[v.new_age]", "column[fruit.processed.age]"],
    ]
    assert "column[name=new_age type=INT properties=[kind=derived_table table=v statement=0]]" in h.nodes_full
    assert "column[name=new_name type=VARCHAR properties=[kind=derived_table table=v statement=0]]" in h.nodes_full
    assert len(h.nodes_full) == 8
    assert len(h.edges) == 6

def test__update_inheritance_only(holder):
    sql = """
    CREATE TABLE fruit.parent (price NUMERIC);
    CREATE TABLE fruit.child () INHERITS (fruit.parent);

    UPDATE ONLY fruit.parent
    SET price = 10;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[10]", "column[fruit.parent.price]"]]
