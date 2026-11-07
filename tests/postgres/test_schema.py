import os
import sys

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.processors.collector.collector import collect_queries
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__create_table_schema_lookup():
    om = mappings.ObjectMapping(dialect=DIALECT)
    collect_queries(text="CREATE TABLE fruit.raw (name TEXT);", dialect=DIALECT, object_mapping=om)

    assert om.lookup_table_query(exp.to_table("fruit.raw")) is not None
    assert om.lookup_schema(exp.to_table("fruit"), raise_on_missing=False) is None

    collect_queries(text="CREATE SCHEMA fruit;", dialect=DIALECT, object_mapping=om)

    assert om.lookup_schema(exp.to_table("fruit")).kind == "schema"


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
