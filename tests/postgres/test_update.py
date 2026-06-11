import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


from sqlleaf.objects.query_types import TableQuery, UpdateQuery

DIALECT = "postgres"


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
    assert [UpdateQuery] == list(map(type, h.queries))
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
    assert [UpdateQuery] == list(map(type, h.queries))


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
    assert [UpdateQuery] == list(map(type, h.queries))


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
    assert [TableQuery, UpdateQuery] == list(map(type, h.queries))


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
    assert [UpdateQuery] == list(map(type, h.queries))


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
    assert [UpdateQuery] == list(map(type, h.queries))


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
    assert h.nodes_full == ["column[name=age table=processed schema=fruit type=INT kind=table]"]
    assert len(h.edges) == 1
    assert [UpdateQuery] == list(map(type, h.queries))


def test__update_with_values(holder):
    sql = """
    UPDATE fruit.processed p
    SET name = v.new_name, age = v.new_age
    FROM (
        VALUES ('apple', 10), ('banana', 20)
    ) AS v(new_name, new_age);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["apple"]', "column[v.new_name]", "column[fruit.processed.name]"],
        ['literal["banana"]', "column[v.new_name]", "column[fruit.processed.name]"],
        ["literal[10]", "column[v.new_age]", "column[fruit.processed.age]"],
        ["literal[20]", "column[v.new_age]", "column[fruit.processed.age]"],
    ]
    assert "column[name=new_age table=v type=INT kind=derived_table]" in h.nodes_full
    assert "column[name=new_name table=v type=VARCHAR kind=derived_table]" in h.nodes_full
    assert len(h.nodes_full) == 8
    assert len(h.edges) == 6


# def test__update_with_subquery_in_from(holder):
#     sql = """
#     UPDATE fruit.processed p
#     SET age = s.max_age
#     FROM (
#         SELECT MAX(age) as max_age, kind
#         FROM fruit.raw
#         GROUP BY kind
#     ) s
#     WHERE p.kind = s.kind;
#     """
#     h = holder(sql=sql, dialect=DIALECT, with_tables=True)
#
#     assert h.paths == [
#         ["column[fruit.raw.age]", "function[MAX]", "column[s.max_age]", "column[fruit.processed.age]"]
#     ]
#     assert [UpdateQuery] == list(map(type, h.queries))


def test__update_inheritance_only(holder):
    sql = """
    CREATE TABLE fruit.parent (price NUMERIC);
    CREATE TABLE fruit.child () INHERITS (fruit.parent);

    UPDATE ONLY fruit.parent
    SET price = 10;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[10]", "column[fruit.parent.price]"]]


def test__update_tuple_assignment(holder):
    sql = """
    UPDATE fruit.processed
    SET (name, age) = ('apple', 10);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["apple"]', "column[fruit.processed.name]"],
        ["literal[10]", "column[fruit.processed.age]"],
    ]


# def test__update_subquery_tuple_assignment(holder):
#     sql = """
#     UPDATE fruit.processed
#     SET (name, age) = (SELECT name, age FROM fruit.raw WHERE id = 1);
#     """
#     h = holder(sql=sql, dialect=DIALECT, with_tables=True)
#
#     assert ["column[fruit.raw.name]", "column[fruit.processed.name]"] in h.paths
#     assert ["column[fruit.raw.age]", "column[fruit.processed.age]"] in h.paths
