import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import holder
from sqlleaf.objects.query_types import UpdateQuery, TableQuery

DIALECT = "postgres"


def test__update_simple(holder):
    sql = """
    UPDATE fruit.processed p
    SET name = 'john', age = r.age
    FROM fruit.raw r;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["john"]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.age]', 'column[fruit.processed.age]']
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
    assert [TableQuery, UpdateQuery] == list(map(type, h.queries))


