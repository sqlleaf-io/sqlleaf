import os
import sys
import typing as t

import pytest
from sqlglot import exp

from sqlleaf.models.query import UserDefinedFunctionQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def to_sql(expressions: t.List[exp.Expr]) -> t.List[str]:
    return [e.sql(dialect="postgres") for e in expressions]


def test__udf_params(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        SELECT 'Hello ' || username;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["Hello world"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello world' AS _col_0) AS name"]

    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after


def test__udf_positional_params(holder):
    sql = """
    CREATE FUNCTION hello(TEXT) RETURNS TEXT AS $$
        SELECT 'Hello ' || COALESCE($1, 'Guest');
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [
        ['literal["Hello "]', "function[DPIPE]", "column[target.name]"],
        ['literal["world"]', "function[COALESCE]", "function[DPIPE]", "column[target.name]"],
        ['literal["Guest"]', "function[COALESCE]", "function[DPIPE]", "column[target.name]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (name) SELECT (SELECT 'Hello ' || COALESCE('world', 'Guest') AS _col_0) AS name"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after


def test__udf_inout_params(holder):
    sql = """
    CREATE FUNCTION hello(INOUT TEXT) AS $$
        SELECT 'Hello ' || $1;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["Hello world"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    # $1 is replaced by 'world'
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello world' AS _col_0) AS name"]

    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after


def test__udf_default_params(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT DEFAULT 'World') RETURNS TEXT AS $$
        SELECT 'Hello ' || $1;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello();
    INSERT INTO target (name) SELECT hello('There');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [
        ['literal["Hello World"]', "column[target.name]"],
        ['literal["Hello There"]', "column[target.name]"],
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello World' AS _col_0) AS name"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    insert_after_2 = ["INSERT INTO target (name) SELECT (SELECT 'Hello There' AS _col_0) AS name"]
    actual_after = [h.holders[3].transformed.statement]
    assert to_sql(actual_after) == insert_after_2


def test__udf_return_parameter(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT LANGUAGE SQL RETURN $1;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello('World');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["World"]', "column[target.age]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    # Expect: INSERT INTO target (age) SELECT (SELECT 'World') AS age;
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 'World' AS World) AS age"]

    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after


def test__udf_any_type_fallback(holder):
    sql = """
    CREATE FUNCTION hello(anyelement) RETURNS anyelement AS $$
        SELECT $1
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello(2);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    # In Postgres, columns from tables take precedence over columns from tables if their names match
    insert_query_1 = h.holders[2]
    insert_after_1 = ['INSERT INTO target (age) SELECT (SELECT 2 AS "2") AS age']
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


# TODO: these skip the execution of the inner queries completely; do not include in lineage
cases = ["STRICT", "RETURNS NULL ON NULL INPUT"]


@pytest.mark.parametrize("case", cases)
def test__udf_null_on_null_input(holder, case: str):
    sql = f"""
    CREATE FUNCTION hello(name TEXT) RETURNS anyelement AS $$
        SELECT $1
    $$
    {case}
    LANGUAGE SQL;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello(null);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    # In Postgres, columns from tables take precedence over columns from tables if their names match
    insert_query_1 = h.holders[2]
    insert_after_1 = ["INSERT INTO target (age) SELECT (SELECT NULL AS _col_0) AS age"]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_parameter_column_precedence(holder):
    sql = """
    CREATE TABLE people(name TEXT);
    CREATE FUNCTION hello(name TEXT) RETURNS TEXT AS $$
        SELECT name FROM people;
    $$ LANGUAGE sql;

    CREATE TABLE target(name INT);
    INSERT INTO target (name) SELECT hello('World');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    # In Postgres, columns from tables take precedence over columns from tables if their names match
    insert_query_1 = h.holders[3]
    insert_after_1 = ["INSERT INTO target (name) SELECT (SELECT people.name AS name FROM people AS people) AS name"]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1
