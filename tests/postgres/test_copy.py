import os
import sys

import pytest
from sqlglot.errors import ParseError

from sqlleaf.models.query import CopyQuery
from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"

simple_table = "CREATE TABLE fruit.simple (name VARCHAR, age INT);"
streams = ["STDIN", "STDOUT"]


@pytest.mark.parametrize("stream", streams)
def test_copy_to_stream(holder, stream):
    sql = f"""
    {simple_table}
    COPY fruit.simple TO {stream};
    """
    h = holder(sql=sql, dialect=DIALECT)

    s = stream.lower()
    assert h.paths == [
        ["column[fruit.simple.name]", f"stream[{s}]"],
        ["column[fruit.simple.age]", f"stream[{s}]"],
    ]
    assert h.nodes_full == [
        f"stream[name={s}]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.STREAM


@pytest.mark.parametrize("stream", streams)
def test_copy_from_stream(holder, stream):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM {stream};
    """
    h = holder(sql=sql, dialect=DIALECT)

    s = stream.lower()
    assert h.paths == [
        [f"stream[{s}]", "column[fruit.simple.age]"],
        [f"stream[{s}]", "column[fruit.simple.name]"],
    ]
    assert h.nodes_full == [
        f"stream[name={s}]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.STREAM
    assert query.target_info.type == SqlObjectType.TABLE


def test_copy_columns_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (age) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.age]", "stream[stdout]"],
    ]
    assert len(h.edges) == 1
    assert h.nodes_full == [
        "stream[name=stdout]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
    ]
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.STREAM


def test_copy_select_column_names_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY (SELECT age, name FROM fruit.simple WHERE age > 10) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.age]", "stream[stdout]"],
        ["column[fruit.simple.name]", "stream[stdout]"],
    ]
    assert len(h.edges) == 2
    assert h.nodes_full == [
        "stream[name=stdout]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.SELECT
    assert query.target_info.type == SqlObjectType.STREAM


def test_copy_select_star_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY (SELECT * FROM fruit.simple WHERE age > 10) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "stream[stdout]"],
        ["column[fruit.simple.age]", "stream[stdout]"],
    ]
    assert h.nodes_full == [
        "stream[name=stdout]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.SELECT
    assert query.target_info.type == SqlObjectType.STREAM


# TODO: COPY (VALUES ('apple', 10), ('banana', (select age from fruit.raw))) TO STDOUT;


# TODO: this should still have lineage
# def test_copy_values_to_stream(holder):
#     sql = f"""
#     {simple_table}
#     COPY (VALUES ('apple', 10), ('banana', 20)) TO STDOUT;
#     """
#     # No lineage because there are no database models involved
#     h = holder(sql=sql, dialect=DIALECT)
#     assert h.paths == []
#     assert len(h.nodes_full) == 0
#     assert len(h.edges) == 0
#     query: CopyQuery = h.holders[1].original
#     assert query.source_info.type == SqlObjectType.VALUES
#     assert query.target_info.type == SqlObjectType.STREAM


def test_copy_insert_returning_to_stream(holder):
    with pytest.raises(ParseError) as e:
        sql = f"""
        {simple_table}
        COPY (INSERT INTO fruit.simple (name) VALUES ('cherry') RETURNING name) TO STDOUT;
        """
        h = holder(sql=sql, dialect=DIALECT)
        assert h.paths == [
            ['literal["cherry"]', "column[fruit.simple.name]", "stream[stdout]"],
        ]
    assert e.value.args[0].startswith("Expecting ). Line 3, Col: 20.")


def test_copy_into_table_from_file(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=/tmp/data.csv]", "column[fruit.simple.name]"],
        ["column[age path=/tmp/data.csv]", "column[fruit.simple.age]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.FILE
    assert query.target_info.type == SqlObjectType.TABLE


def test_copy_into_table_from_file_named_columns(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (name, age) FROM '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=/tmp/data.csv]", "column[fruit.simple.name]"],
        ["column[age path=/tmp/data.csv]", "column[fruit.simple.age]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.FILE
    assert query.target_info.type == SqlObjectType.TABLE


def test_copy_into_file_from_table(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple TO '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "column[name path=/tmp/data.csv]"],
        ["column[fruit.simple.age]", "column[age path=/tmp/data.csv]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.FILE


def test_copy_into_file_from_table_named_columns(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (name, age) TO '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "column[name path=/tmp/data.csv]"],
        ["column[fruit.simple.age]", "column[age path=/tmp/data.csv]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.FILE


def test_copy_select_column_names_to_file(holder):
    sql = f"""
    {simple_table}
    COPY (SELECT age, name FROM fruit.simple WHERE age > 10) TO '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.age]", "column[age path=/tmp/data.csv]"],
        ["column[fruit.simple.name]", "column[name path=/tmp/data.csv]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.SELECT
    assert query.target_info.type == SqlObjectType.FILE


def test_copy_select_column_aliases_to_file(holder):
    sql = f"""
    {simple_table}
    COPY (
        SELECT age AS a, age, name AS b FROM fruit.simple WHERE age > 10
    ) TO '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.age]", "column[a path=/tmp/data.csv]"],
        ["column[fruit.simple.age]", "column[age path=/tmp/data.csv]"],
        ["column[fruit.simple.name]", "column[b path=/tmp/data.csv]"],
    ]
    assert h.nodes_full == [
        "column[name=a type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=b type=VARCHAR properties=[kind=file format=TEXT path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 3
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.SELECT
    assert query.target_info.type == SqlObjectType.FILE

    expected_query = (
        "INSERT INTO '/tmp/data.csv' (a, age, b) "
        "SELECT simple.age AS a, simple.age AS age, simple.name AS b "
        "FROM fruit.simple AS simple "
        "WHERE simple.age > 10"
    )
    copy_holder = h.lineage.collected_queries.queries[1]
    assert copy_holder.transformed.statement.sql(dialect=DIALECT) == expected_query


def test_copy_select_join_to_stream(holder):
    extra_table = "CREATE TABLE fruit.extra (name VARCHAR, color VARCHAR);"
    sql = f"""
    {simple_table}
    {extra_table}
    COPY (
        SELECT UPPER(s.name) AS name, s.age, e.color
        FROM fruit.simple AS s
        JOIN fruit.extra AS e ON s.name = e.name
    ) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "function[UPPER]", "stream[stdout]"],
        ["column[fruit.simple.age]", "stream[stdout]"],
        ["column[fruit.extra.color]", "stream[stdout]"],
    ]
    assert h.nodes_full == [
        "function[name=UPPER type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "stream[name=stdout]",
        "column[name=color type=VARCHAR properties=[kind=table table=extra schema=fruit]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 4
    query: CopyQuery = h.holders[2].transformed
    assert query.source_info.type == SqlObjectType.SELECT
    assert query.target_info.type == SqlObjectType.STREAM


def test_copy_into_program_from_table(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple TO PROGRAM 'gzip > /tmp/data.csv.gz';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "program[gzip]"],
        ["column[fruit.simple.age]", "program[gzip]"],
    ]
    assert h.nodes_full == [
        "program[name=gzip properties=[args='> /tmp/data.csv.gz'] position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.PROGRAM


def test_copy_table_program_from_program(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM PROGRAM 'cat /tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["program[cat]", "column[fruit.simple.age]"],
        ["program[cat]", "column[fruit.simple.name]"],
    ]
    assert h.nodes_full == [
        "program[name=cat properties=[args='/tmp/data.csv'] position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.holders[1].transformed
    assert query.source_info.type == SqlObjectType.PROGRAM
    assert query.target_info.type == SqlObjectType.TABLE


def test_copy_with_format_csv(holder):
    sql = """
    CREATE TABLE fruit.simple (name VARCHAR, age INT);
    COPY fruit.simple FROM '/tmp/data.csv' WITH (FORMAT csv);
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=/tmp/data.csv]", "column[fruit.simple.name]"],
        ["column[age path=/tmp/data.csv]", "column[fruit.simple.age]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=file format=csv path=/tmp/data.csv]]",
        "column[name=name type=VARCHAR properties=[kind=file format=csv path=/tmp/data.csv]]",
        "column[name=age type=INT properties=[kind=table table=simple schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=simple schema=fruit]]",
    ]
    query: CopyQuery = h.holders[1].original
    assert query.parameters.file_format.lower() == "csv"


# TODO: COPY FROM SELECT * FROM UDF()
