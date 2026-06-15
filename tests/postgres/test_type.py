import os
import sys

from sqlleaf.models.query import TypeQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


# Composite type with multiple fields
def test_type_composite(holder):
    sql = """
    CREATE TYPE fruit AS (
        name VARCHAR,
        age INT
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert [TypeQuery] == list(map(type, h.queries))


# Composite type with schema qualification
def test_type_composite_schema(holder):
    sql = """
    CREATE TYPE fruit.new AS (
        name VARCHAR,
        age INT
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert [TypeQuery] == list(map(type, h.queries))


# Composite type with a nested type
def test_type_composite_nested(holder):
    sql = """
    CREATE TYPE fruit AS (
        name VARCHAR,
        species species
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert [TypeQuery] == list(map(type, h.queries))


# Enum type with multiple labels
def test_type_enum(holder):
    sql = """
    CREATE TYPE fruit AS ENUM ('apple', 'banana', 'cherry');
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert [TypeQuery] == list(map(type, h.queries))


# Enum type with a single label
def test_type_enum_single(holder):
    sql = """
    CREATE TYPE fruit AS ENUM ('apple', 'banana', 'cherry');
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert [TypeQuery] == list(map(type, h.queries))


# Range type
def test_type_range(holder):
    sql = """
    CREATE TYPE float8_range AS RANGE (
        subtype = float8,
        subtype_diff = float8mi
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.queries) == 0
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


# Multirange type
def test_type_multirange(holder):
    sql = """
    CREATE TYPE float8_multirange AS MULTIRANGE (
        subtype = float8_range
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.queries) == 0
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


# Base type
def test_type_base(holder):
    sql = """
    CREATE TYPE fruit (
        INPUT = fruit_in,
        OUTPUT = fruit_out,
        INTERNALLENGTH = 16
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert len(h.queries) == 0
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


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
    assert h.queries
    assert TypeQuery == list(map(type, h.queries))[0]
