import os
import sys

import pytest
from sqlglot.errors import ParseError

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

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
        ['column[fruit.simple.name]', f'stream[{s}]'],
        ['column[fruit.simple.age]', f'stream[{s}]'],
    ]
    assert h.nodes_full == [
        f'stream[{s}]',
        'column[fruit.simple.age type=INT kind=table]',
        'column[fruit.simple.name type=VARCHAR kind=table]',
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
        [f'stream[{s}]', 'column[fruit.simple.age]'],
        [f'stream[{s}]', 'column[fruit.simple.name]'],
    ]
    assert h.nodes_full == [
        f'stream[{s}]',
        'column[fruit.simple.age type=INT kind=table]',
        'column[fruit.simple.name type=VARCHAR kind=table]',
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


def test_copy_select_column_names_to_stream(holder):
    sql = f"""
    {simple_table}
    COPY (SELECT age, name FROM fruit.simple WHERE age > 10) TO STDOUT;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[fruit.simple.name]", "stream[stdout]"],
        ["column[fruit.simple.age]", "stream[stdout]"],
    ]


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
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.queries) == 2


def test_copy_insert_returning_to_stream(holder):
    with pytest.raises(ParseError) as e:
        sql = f"""
        {simple_table}
        COPY (INSERT INTO fruit.simple (name) VALUES ('cherry') RETURNING name) TO STDOUT;
        """
        h = holder(sql=sql, dialect=DIALECT)
        assert h.paths == [
            ['literal["cherry"]', "stream[stdout]"],
        ]
    assert e.value.args[0].startswith("Expecting ). Line 3, Col: 20.")


def test_copy_target_table(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['column[name path=/tmp/data.csv]', 'column[fruit.simple.name]'],
        ['column[age path=/tmp/data.csv]', 'column[fruit.simple.age]']
    ]
    assert h.nodes_full == [
        'column[age type=INT kind=file format=csv path=/tmp/data.csv]',
        'column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]',
        'column[fruit.simple.age type=INT kind=table]',
        'column[fruit.simple.name type=VARCHAR kind=table]'
    ]


def test_copy_target_table_named_columns(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (name, age) FROM '/tmp/data.csv';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['column[name path=/tmp/data.csv]', 'column[fruit.simple.name]'],
        ['column[age path=/tmp/data.csv]', 'column[fruit.simple.age]']
    ]
    assert h.nodes_full == [
        'column[age type=INT kind=file format=csv path=/tmp/data.csv]',
        'column[name type=VARCHAR kind=file format=csv path=/tmp/data.csv]',
        'column[fruit.simple.age type=INT kind=table]',
        'column[fruit.simple.name type=VARCHAR kind=table]'
    ]


def test_copy_target_program(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple TO PROGRAM 'gzip > /tmp/data.csv.gz';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['column[fruit.simple.name]', 'program[gzip]'],
        ['column[fruit.simple.age]', 'program[gzip]'],
    ]
    assert h.nodes_full == [
        "program[gzip args='> /tmp/data.csv.gz']",
        'column[fruit.simple.age type=INT kind=table]',
        'column[fruit.simple.name type=VARCHAR kind=table]',
    ]
