import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = "postgres"


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
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"]
    ]
    assert len(h.nodes) == 4
    assert len(h.queries) == 1
    assert [UpdateQuery, InsertQuery] == list(map(type, h.queries[0].child_queries))
    assert (
        h.queries[0].child_queries[0].statement_transformed.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (name) SELECT s.name AS name FROM fruit.raw AS s"
    )
    assert (
        h.queries[0].child_queries[1].statement_transformed.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"
    )


# TODO: test MERGE USING (SELECT ...)
# TODO: test two merge queries that have an identical inner query
#  expect: the two inner queries are identical (and preserved), but they have different parents
