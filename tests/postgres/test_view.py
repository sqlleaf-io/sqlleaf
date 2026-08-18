import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__view_materialized(holder):
    sql = """CREATE MATERIALIZED VIEW one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[-1]", "column[one.number]"]]
    assert "column[name=number type=INT properties=[kind=view subkind=materialized table=one]]" in h.nodes_full
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
