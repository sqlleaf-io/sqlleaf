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


def test__temporary_sequence_schema_and_flag(holder):
    sql = """
    CREATE TEMPORARY SEQUENCE temp_serial START 101;
    CREATE SEQUENCE serial START 101;
    """
    h = holder(sql=sql, dialect=DIALECT)

    temp_query, perm_query = h.queries_original
    assert isinstance(temp_query, SequenceQuery)
    assert temp_query.target_info.expression.sql() == "pg_temp.temp_serial"
    assert temp_query.temporary
    assert perm_query.target_info.expression.sql() == "public.serial"
    assert not perm_query.temporary


def test__sequence_explicit_pg_temp_schema_is_temporary(holder):
    sql = """CREATE SEQUENCE pg_temp.explicit_serial START 101;"""
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries_original[0]
    assert query.target_info.expression.sql() == "pg_temp.explicit_serial"
    assert query.temporary

def test__sequence_function_qualifies_temporary_sequence(holder):
    sql = """
    CREATE TEMPORARY SEQUENCE ts START 1;
    CREATE TABLE t AS SELECT nextval('ts') AS id;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert "sequence[name=ts type=INT properties=[subkind=temporary]]" in h.nodes_full


def test__sequence_function_explicit_pg_temp_schema(holder):
    sql = """
    CREATE TEMPORARY SEQUENCE ts START 1;
    CREATE TABLE t AS SELECT nextval('pg_temp.ts') AS id;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert "sequence[name=ts type=INT properties=[subkind=temporary]]" in h.nodes_full


def test__sequence_function_permanent_sequence(holder):
    sql = """
    CREATE SEQUENCE perm_seq START 1;
    CREATE TABLE t AS SELECT nextval('perm_seq') AS id;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["sequence[perm_seq]", "column[public.t.id]"]]
