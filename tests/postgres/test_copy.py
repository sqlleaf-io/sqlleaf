import os
import sys

import pytest
from sqlglot.errors import ParseError

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
        f"stream[{s}]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        f"stream[{s}]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


def test_copy_columns_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (age, name) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "stream[stdout]"],
        ["column[fruit.simple.age]", "stream[stdout]"],
    ]
    assert len(h.edges) == 2


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


def test_copy_values_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY (VALUES ('apple', 10), ('banana', 20)) TO STDOUT;
    """
    # No lineage because there are no database objects involved
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes_full) == 0
    assert len(h.edges) == 0


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
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


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
        "column[a type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[age type=INT kind=file format=csv path=/tmp/data.csv]",
        "column[b type=VARCHAR kind=file format=csv path=/tmp/data.csv]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 3

    expected_query = (
        "INSERT INTO '/tmp/data.csv' (a, age, b) "
        "SELECT simple.age AS a, simple.age AS age, simple.name AS b "
        "FROM fruit.simple AS simple "
        "WHERE simple.age > 10"
    )
    assert h.queries[1].statement_transformed.sql(dialect=DIALECT) == expected_query


def test_copy_select_join_to_stream(holder):
    extra_table = "CREATE TABLE fruit.extra (name VARCHAR, color VARCHAR);"
    sql = f"""
    {simple_table}
    {extra_table}
    COPY (
        SELECT s.name, s.age, e.color
        FROM fruit.simple AS s
        JOIN fruit.extra AS e ON s.name = e.name
    ) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "stream[stdout]"],
        ["column[fruit.simple.age]", "stream[stdout]"],
        ["column[fruit.extra.color]", "stream[stdout]"],
    ]
    assert h.nodes_full == [
        "stream[stdout]",
        "column[name=color table=extra schema=fruit type=VARCHAR kind=table]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 3


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
        "program[gzip args='> /tmp/data.csv.gz']",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


# TODO: COPY FROM PROGRAM
