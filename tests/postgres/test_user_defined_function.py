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


def test_hello_udf(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE sql;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries[0]
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [["udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.queries[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello') AS name"]

    actual_after = [insert_query.statement_substituted]
    assert to_sql(actual_after) == insert_after


def test_hello_schema_udf(holder):
    sql = """
    CREATE FUNCTION greetings.hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE sql;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT greetings.hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries[0]
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name == "greetings"
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [["udf[GREETINGS.HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.queries[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello') AS name"]

    actual_after = [insert_query.statement_substituted]
    assert to_sql(actual_after) == insert_after


def test_hello_params_udf(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        SELECT 'Hello ' || username;
    $$ LANGUAGE sql;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries[0]
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [
        ['literal["world"]', "udf[HELLO]", "column[target.name]"]
    ]
    assert len(h.nodes) == 3 # 'world', HELLO, target.name
    assert len(h.edges) == 2

    insert_query = h.queries[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'world') AS name"]

    actual_after = [insert_query.statement_substituted]
    assert to_sql(actual_after) == insert_after


def test_hello_positional_params_udf(holder):
    sql = """
    CREATE FUNCTION hello(TEXT) RETURNS TEXT AS $$
        SELECT 'Hello ' || COALESCE($1, 'Guest');
    $$ LANGUAGE sql RETURNS NULL ON NULL INPUT;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries[0]
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    # Lineage path: literal 'world' -> udf[HELLO] -> column[target.name]
    assert h.paths == [
        ['literal["world"]', "udf[HELLO]", "column[target.name]"]
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.queries[2]
    # $1 is replaced by 'world'
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || COALESCE('world', 'Guest')) AS name"]

    actual_after = [insert_query.statement_substituted]
    assert to_sql(actual_after) == insert_after


def test_hello_inout_params_udf(holder):
    sql = """
    CREATE FUNCTION hello(INOUT TEXT) AS $$
        SELECT 'Hello ' || $1;
    $$ LANGUAGE sql;

    CREATE TABLE target(name VARCHAR);
    INSERT INTO target (name) SELECT hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries[0]
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    # INOUT TEXT means the return type is TEXT
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    # Lineage path: literal 'world' -> udf[HELLO] -> column[target.name]
    assert h.paths == [
        ['literal["world"]', "udf[HELLO]", "column[target.name]"]
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2

    insert_query = h.queries[2]
    # $1 is replaced by 'world'
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'world') AS name"]

    actual_after = [insert_query.statement_substituted]
    assert to_sql(actual_after) == insert_after
