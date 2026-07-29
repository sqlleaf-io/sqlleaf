import os
import sys
import typing as t

from sqlglot import exp

from sqlleaf.models.query import UserDefinedFunctionQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def to_sql(expressions: t.List[exp.Expr]) -> t.List[str]:
    return [e.sql(dialect="postgres") for e in expressions]


def test__udf_simple(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello' AS Hello) AS name"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__udf_schema(holder):
    sql = """
    CREATE FUNCTION greetings.hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT greetings.hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name == "greetings"
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello' AS Hello) AS name"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__udf_schema_distinction(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT LANGUAGE SQL RETURN 'no_schema';
    CREATE FUNCTION greetings.hello() RETURNS TEXT LANGUAGE SQL RETURN 'yes_schema';

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello();
    INSERT INTO target (age) SELECT greetings.hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    udf1 = h.holders[0].original
    assert isinstance(udf1, UserDefinedFunctionQuery)
    assert udf1.function_name == "hello"
    assert udf1.schema_name is None

    udf2 = h.holders[1].original
    assert isinstance(udf2, UserDefinedFunctionQuery)
    assert udf2.function_name == "hello"
    assert udf2.schema_name == "greetings"

    assert to_sql([h.holders[3].transformed.statement]) == [
        "INSERT INTO target (age) SELECT (SELECT 'no_schema' AS no_schema) AS age"
    ]
    assert to_sql([h.holders[4].transformed.statement]) == [
        "INSERT INTO target (age) SELECT (SELECT 'yes_schema' AS yes_schema) AS age"
    ]

    assert h.paths == [
        ['literal["no_schema"]', "column[target.age]"],
        ['literal["yes_schema"]', "column[target.age]"],
    ]


def test__udf_select(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello' AS Hello) AS name"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__udf_values(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) VALUES(hello());
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello' AS Hello) AS name"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello"]', "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
