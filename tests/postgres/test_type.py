import os
import sys

import pytest

from sqlleaf.models.query import TypeQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


schemas = ["", "food."]


@pytest.mark.parametrize("case", schemas)
def test_type_composite(holder, case: str):
    sql = f"""
    CREATE TYPE {case}fruit AS (
        name VARCHAR,
        age INT
    );
    CREATE TABLE target (name {case}fruit);
    INSERT INTO target (name) SELECT ROW('apple', 5);
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['literal["apple"]', "udf[ROW]", "column[target.name]"],
        ["literal[5]", "udf[ROW]", "column[target.name]"],
    ]
    assert h.nodes_full == [
        'literal["apple" type=VARCHAR query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]',
        "literal[5 type=INT query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=1]",
        "udf[ROW type=UNKNOWN query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]",
        f"column[name=name table=target type={case}fruit kind=table]",
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3
    assert [TypeQuery] == h.query_types[:1]


def test_type_composite_nested(holder):
    sql = """
    CREATE TYPE status AS (
        kind VARCHAR
    );
    CREATE TYPE fruit AS (
        name VARCHAR,
        status status
    );
    CREATE TABLE target (some fruit);
    INSERT INTO target (some) SELECT ROW('apple', ROW('new'))::fruit;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['literal["apple"]', "udf[ROW]", "function[CAST]", "column[target.some]"],
        ['literal["new"]', "udf[ROW]", "udf[ROW]", "function[CAST]", "column[target.some]"],
    ]
    assert h.nodes_full == [
        'literal["apple" type=VARCHAR query_depth=0 query_width=0 statement=3 select=0 func_depth=2 func_arg=0]',
        'literal["new" type=VARCHAR query_depth=0 query_width=0 statement=3 select=0 func_depth=3 func_arg=1]',
        "function[CAST type=fruit query_depth=0 query_width=0 statement=3 select=0 func_depth=0 func_arg=0]",
        "udf[ROW type=UNKNOWN query_depth=0 query_width=0 statement=3 select=0 func_depth=1 func_arg=0]",
        "udf[ROW type=UNKNOWN query_depth=0 query_width=0 statement=3 select=0 func_depth=2 func_arg=1]",
        "column[name=some table=target type=fruit kind=table]",
    ]
    assert len(h.edges) == 5
    assert [TypeQuery, TypeQuery] == h.query_types[:2]


def test_type_enum(holder):
    sql = """
    CREATE TYPE fruit_enum AS ENUM ('apple', 'banana', 'cherry');
    CREATE TABLE target (name fruit_enum);
    INSERT INTO target (name) SELECT 'apple';
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [['literal["apple"]', "column[target.name]"]]
    assert h.nodes_full == [
        'literal["apple" type=VARCHAR query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        "column[name=name table=target type=fruit_enum kind=table]",
    ]
    assert len(h.edges) == 1
    assert [TypeQuery] == h.query_types[:1]


# Unsupported syntax
def test_type_range(holder):
    sql = """
    CREATE FUNCTION time_subtype_diff(x time, y time)
    RETURNS float8 AS
        'SELECT EXTRACT(EPOCH FROM (x - y))'
    LANGUAGE sql STRICT IMMUTABLE;

    CREATE TYPE timerange AS RANGE (
        subtype = time,
        subtype_diff = time_subtype_diff
    );
    CREATE TABLE my_time (t timerange);

    INSERT INTO my_time (t) SELECT '[11:10, 23:00]'::timerange;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


# Unsupported syntax
def test_type_multirange(holder):
    sql = """
    CREATE TYPE float8_multirange AS MULTIRANGE (
        subtype = float8_range
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


# Test referencing a custom type in CREATE TABLE and INSERT
def test_type_usage_in_table_and_insert(holder):
    sql = """
    CREATE TYPE fruit AS ENUM ('apple', 'banana', 'cherry');
    CREATE TABLE recipe (food fruit);

    INSERT INTO recipe (food)
    SELECT 'apple'::fruit;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['literal["apple"]', "function[CAST]", "column[recipe.food]"]]
    assert h.nodes_full == [
        'literal["apple" type=VARCHAR query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]',
        "function[CAST type=fruit query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]",
        "column[name=food table=recipe type=fruit kind=table]",
    ]
    assert len(h.edges) == 2
    assert TypeQuery == h.query_types[0]
