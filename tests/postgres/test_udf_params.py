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

    assert h.paths == [['literal["world"]', "udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 3  # 'world', HELLO, target.name
    assert len(h.edges) == 2

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello world' AS _col_0) AS name"]

    actual_after = [insert_query.child_holders[0].transformed.statement]
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

    assert h.paths == [['literal["world"]', "udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || COALESCE('world', 'Guest') AS _col_0) AS name"]

    actual_after = [insert_query.child_holders[0].transformed.statement]
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

    assert h.paths == [['literal["world"]', "udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.holders[2]
    # $1 is replaced by 'world'
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello world' AS _col_0) AS name"]

    actual_after = [insert_query.child_holders[0].transformed.statement]
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

    assert h.paths == [["udf[HELLO]", "column[target.name]"], ['literal["There"]', "udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello World' AS _col_0) AS name"]
    actual_after = [insert_query.child_holders[0].transformed.statement]
    assert to_sql(actual_after) == insert_after

    insert_after_2 = ["INSERT INTO target (name) SELECT (SELECT 'Hello There' AS _col_0) AS name"]
    actual_after = [h.holders[3].child_holders[0].transformed.statement]
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

    assert h.paths == [['literal["World"]', "udf[HELLO]", "column[target.age]"]]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.holders[2]
    # Expect: INSERT INTO target (age) SELECT (SELECT 'World') AS age;
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 'World' AS World) AS age"]

    actual_after = [insert_query.child_holders[0].transformed.statement]
    assert to_sql(actual_after) == insert_after


def test__udf_variadic_parameter(holder):
    sql = """
    CREATE FUNCTION hello(greeting TEXT, VARIADIC names TEXT[])
    RETURNS TEXT AS $$
        SELECT greeting || ' ' || string_agg(unpacked_name, ' and ')
        FROM unnest(names) AS unpacked_name;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name1 VARCHAR);
    INSERT INTO target (name1) SELECT hello('Hi', 'Alice', 'Bob', 'Charlie');
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_columns == []
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert len(query.parameters) == 2
    assert query.parameters[0].name == "greeting"
    assert not query.parameters[0].is_variadic
    assert query.parameters[1].name == "names"
    assert query.parameters[1].is_variadic

    assert sorted(h.paths) == sorted([
        ['literal["Hi"]', "udf[HELLO]", "column[target.name1]"],
        ['literal["Alice"]', "udf[HELLO]", "column[target.name1]"],
        ['literal["Bob"]', "udf[HELLO]", "column[target.name1]"],
        ['literal["Charlie"]', "udf[HELLO]", "column[target.name1]"],
    ])

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (name1) SELECT (SELECT 'Hi ' || STRING_AGG(unpacked_name.unpacked_name, ' and ') AS _col_0 FROM UNNEST(ARRAY['Alice', 'Bob', 'Charlie']) AS unpacked_name) AS name1"
    ]
    actual_after_1 = [insert_query_1.child_holders[0].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_mleast_variadic_parameter(holder):
    sql = """
    CREATE FUNCTION mleast(VARIADIC arr numeric[]) RETURNS numeric AS $$
        SELECT min($1[i]) FROM generate_subscripts($1, 1) g(i);
    $$ LANGUAGE SQL;

    CREATE TABLE target(age INT);
    -- Variadic args
    INSERT INTO target (age) SELECT mleast(10, -1, 5, 4.4);
    -- Variadic array
    INSERT INTO target (age) SELECT mleast(VARIADIC ARRAY[10, -1, 5, 4.4]);
    -- Empty array
    INSERT INTO target (age) SELECT mleast(VARIADIC ARRAY[]::numeric[]);
    -- Variadic array from CTE
    INSERT INTO target (age)
    WITH data_source AS (
        SELECT ARRAY[10, -1, 5, 4.4]::numeric[] AS my_array
    )
    SELECT mleast(VARIADIC my_array) FROM data_source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "mleast"
    assert query.schema_name is None
    assert query.return_columns == []
    assert query.return_type == exp.DataType.build("numeric")
    assert query.language == "sql"

    assert len(query.parameters) == 1
    assert query.parameters[0].name == "arr"
    assert query.parameters[0].is_variadic

    assert sorted(h.paths) == sorted([
        ["literal[10]", "udf[MLEAST]", "column[target.age]"],
        ["literal[-1]", "udf[MLEAST]", "column[target.age]"],
        ["literal[5]", "udf[MLEAST]", "column[target.age]"],
        ["literal[4.4]", "udf[MLEAST]", "column[target.age]"],
        ["literal[{10,-1,5,4.4}]", "udf[MLEAST]", "column[target.age]"],
        ["literal[{}]", "function[CAST]", "udf[MLEAST]", "column[target.age]"],
        [
            "literal[{10,-1,5,4.4}]",
            "function[CAST]",
            "column[data_source.my_array]",
            "udf[MLEAST]",
            "column[target.age]",
        ],
    ])

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after_1 = [insert_query_1.child_holders[0].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1

    insert_query_2 = h.holders[3]
    insert_after_2 = [
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after_2 = [insert_query_2.child_holders[0].transformed.statement]
    assert to_sql(actual_after_2) == insert_after_2

    insert_query_3 = h.holders[4]
    insert_after_3 = [
        "INSERT INTO target (age) SELECT (SELECT MIN((CAST(ARRAY[] AS DECIMAL[]))[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(CAST(ARRAY[] AS DECIMAL[]), 1) AS g(i)) AS age"
    ]
    actual_after_3 = [insert_query_3.child_holders[0].transformed.statement]
    assert to_sql(actual_after_3) == insert_after_3

    insert_query_4 = h.holders[5]
    insert_after_4 = [
        "INSERT INTO target (age) WITH data_source AS (SELECT CAST(ARRAY[10, -1, 5, 4.4] AS DECIMAL[]) AS my_array) SELECT (SELECT MIN(data_source.my_array[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(my_array, 1) AS g(i)) AS age FROM data_source AS data_source"
    ]
    actual_after_4 = [insert_query_4.child_holders[0].transformed.statement]
    assert to_sql(actual_after_4) == insert_after_4


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
    insert_after_1 = ["INSERT INTO target (age) SELECT (SELECT 2 AS \"2\") AS age"]
    actual_after_1 = [insert_query_1.child_holders[0].transformed.statement]
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
    actual_after_1 = [insert_query_1.child_holders[0].transformed.statement]
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
    actual_after_1 = [insert_query_1.child_holders[0].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1
