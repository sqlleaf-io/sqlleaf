import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder, DIALECT
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = "postgres"


def test__merge_simple_update_and_insert(holder):
    queries = """
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()

    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert paths == [["column[fruit.raw.name]", "column[fruit.processed.name]"], ["column[fruit.raw.kind]", "column[fruit.processed.label]"]]
    assert len(nodes) == 4
    assert len(queries) == 1
    assert [UpdateQuery, InsertQuery] == list(map(type, queries[0].child_queries))
    assert (
        queries[0].child_queries[0].statement_transformed.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (name) SELECT s.name AS name FROM fruit.raw AS s"
    )
    assert (
        queries[0].child_queries[1].statement_transformed.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )


# TODO: test MERGE USING (SELECT ...)
# TODO: test two merge queries that have an identical inner query
#  expect: the two inner queries are identical (and preserved), but they have different parents
