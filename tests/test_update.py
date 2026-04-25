import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import holder
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery, TableQuery

DIALECT = "postgres"


def test__update_with_subquery(holder):
    queries = """
    UPDATE fruit.processed
    SET amount = (
        SELECT COUNT(kind)
        FROM fruit.raw
    ), age = 5;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert paths == [
        ["literal[5]", "column[fruit.processed.age]"],
        ["column[fruit.raw.kind]", "function[COUNT()]", "column[fruit.processed.amount]"],
    ]
    assert [UpdateQuery] == list(map(type, queries))


def test__update_with_join(holder):
    queries = """
    UPDATE fruit.processed p
    SET age = r.age
    FROM fruit.raw r
    WHERE p.name = r.name;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert paths == [["column[fruit.raw.age]", "column[fruit.processed.age]"]]
    assert [UpdateQuery] == list(map(type, queries))


def test__update_with_multiple_joins(holder):
    queries = """
    CREATE TABLE fruit.old (name VARCHAR);

    UPDATE fruit.processed p
    SET age = r.age
    FROM fruit.raw r
    JOIN fruit.old o
    ON r.name = o.name
    WHERE p.name = r.name;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert paths == [["column[fruit.raw.age]", "column[fruit.processed.age]"]]
    assert [TableQuery, UpdateQuery] == list(map(type, queries))
