import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__schema(holder):
    sql = """
    CREATE SCHEMA food;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.queries) == 1


def test__schema_with_tables(holder):
    sql = """
    CREATE SCHEMA hollywood
    CREATE TABLE films (title text, release date, awards text[])
    CREATE VIEW winners AS
        SELECT title, release FROM films WHERE awards IS NOT NULL;

    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1
