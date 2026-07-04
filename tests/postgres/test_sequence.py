import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import InsertQuery, SequenceQuery

DIALECT = "postgres"


def test__simple_sequence(holder):
    sql = """
    CREATE SEQUENCE serial START 101;
    INSERT INTO fruit.raw (age) SELECT nextval('serial') as age;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["sequence[serial]", "column[fruit.raw.age]"]]
    assert [SequenceQuery, InsertQuery] == h.query_types
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__temporary_sequence(holder):
    sql = """
    CREATE TEMPORARY SEQUENCE temp_serial START 101;
    INSERT INTO fruit.raw (age) SELECT nextval('temp_serial') as age;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["sequence[temp_serial]", "column[fruit.raw.age]"]]
    assert "sequence[name=temp_serial type=INT properties=[subkind=temporary]]" in h.nodes_full
    assert [SequenceQuery, InsertQuery] == h.query_types
