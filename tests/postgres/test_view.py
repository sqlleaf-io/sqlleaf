import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__view_materialized(holder):
    sql = """CREATE MATERIALIZED VIEW fruit.one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[-1]", "column[fruit.one.number]"]]
    assert "column[name=number type=INT properties=[kind=view subkind=materialized table=one schema=fruit]]" in h.nodes_full
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
    assert h.queries_transformed[0].statement.sql() == "CREATE MATERIALIZED VIEW fruit.one AS SELECT -1 AS number"


def test__view_no_schema_adds_default_schema(holder):
    sql = """
    CREATE VIEW new AS SELECT 1 AS name;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[1]", "column[public.new.name]"]]
    assert h.queries_transformed[0].statement.sql() == "CREATE VIEW public.new AS SELECT 1 AS name"
