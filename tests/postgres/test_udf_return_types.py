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


def test__udf_void_return(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS void AS 'SELECT 1;' LANGUAGE SQL;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("NULL")
    assert query.language == "sql"

    assert h.paths == [["null[NULL]", "column[target.age]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (age) SELECT (SELECT NULL AS _col_0) AS age"]

    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after


# If a function returns more than one column, ensure that its 'returned column names' are the name of the parameter (if provided)
# or 'column<N>' if no name is provided, where N is the position of the parameter in the function's list.


def test__udf_inout_parameter(holder):
    sql = """
    CREATE FUNCTION hello(INOUT username TEXT DEFAULT 'User', INOUT TEXT DEFAULT 'Hi') AS $$
        SELECT $2 || ' ' || $1, 'Goodbye ' || $1;
    $$ LANGUAGE SQL;

    CREATE TABLE target(msg VARCHAR, bye VARCHAR);
    INSERT INTO target (msg, bye) SELECT * FROM hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    # Multiple INOUT parameters means it returns a set of columns (effectively a table)
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("username"), kind=exp.DType.TEXT.into_expr()),
        exp.ColumnDef(this=exp.to_identifier("column2"), kind=exp.DType.TEXT.into_expr()),
    ]
    assert query.language == "sql"

    # Check substitution for the first INSERT
    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (msg, bye) SELECT hello.username AS msg, hello.column2 AS bye FROM (SELECT 'Hi User' AS username, 'Goodbye User' AS column2) AS hello"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_in_out_inout_parameters(holder):
    sql = """
    CREATE FUNCTION hello(
        IN username TEXT,
        INOUT middle_name TEXT,
        OUT last_name VARCHAR
    ) AS $$
        SELECT UPPER(middle_name), LOWER(username);
    $$ LANGUAGE SQL;

    CREATE TABLE target(name1 VARCHAR, name2 VARCHAR);
    INSERT INTO target(name1, name2) SELECT * FROM hello(username => 'Hello', middle_name => 'There');
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    # Multiple INOUT parameters means it returns a set of columns (effectively a table)
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("middle_name"), kind=exp.DType.TEXT.into_expr()),
        exp.ColumnDef(this=exp.to_identifier("last_name"), kind=exp.DType.VARCHAR.into_expr()),
    ]
    assert query.language == "sql"

    # Check substitution for the first INSERT
    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (name1, name2) SELECT hello.middle_name AS name1, hello.last_name AS name2 FROM (SELECT UPPER('There') AS middle_name, LOWER('Hello') AS last_name) AS hello"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_table_no_params(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TABLE(property TEXT, value TEXT) AS $$
        SELECT 'prop', 'val';
    $$ LANGUAGE SQL;
    CREATE TABLE target(name1 VARCHAR, name2 VARCHAR, age INT);
    INSERT INTO target (name1, name2) SELECT * FROM hello();
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    # Multiple INOUT parameters means it returns a set of columns (effectively a table)
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("property"), kind=exp.DType.TEXT.into_expr()),
        exp.ColumnDef(this=exp.to_identifier("value"), kind=exp.DType.TEXT.into_expr()),
    ]
    assert query.language == "sql"

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (name1, name2) SELECT hello.property AS name1, hello.value AS name2 FROM (SELECT 'prop' AS property, 'val' AS value) AS hello"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_table_and_values(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TABLE(property TEXT, value TEXT) AS $$
        VALUES ('greeting', 'Hello ' || username)
    $$ LANGUAGE SQL;

    CREATE TABLE target(name1 VARCHAR, name2 VARCHAR, age INT);
    INSERT INTO target (name1, name2, age) SELECT *, 1 FROM hello('John');
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("property"), kind=exp.DType.TEXT.into_expr()),
        exp.ColumnDef(this=exp.to_identifier("value"), kind=exp.DType.TEXT.into_expr()),
    ]
    assert query.language == "sql"

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (name1, name2, age) SELECT hello.property AS name1, hello.value AS name2, 1 AS age FROM (SELECT 'greeting' AS property, 'Hello John' AS value) AS hello"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_composite_type(holder):
    sql = """
    CREATE TYPE person AS (name1 TEXT, age1 INT);
    CREATE FUNCTION hello (text) RETURNS person AS $$
        SELECT $1, 50;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR, age INT);
    INSERT INTO target (name, age) SELECT * FROM hello('John');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type.this == exp.DataType.Type.USERDEFINED
    assert query.return_type.args["kind"].this == "person"
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("name1"), kind=exp.DataType.build("TEXT")),
        exp.ColumnDef(this=exp.to_identifier("age1"), kind=exp.DataType.build("INT")),
    ]
    assert query.language == "sql"

    assert sorted(h.paths) == [
        ['literal["John"]', "column[hello.name1]", "column[target.name]"],
        ["literal[50]", "column[hello.age1]", "column[target.age]"],
    ]

    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name1 AS name, hello.age1 AS age FROM (SELECT 'John' AS name1, 50 AS age1) AS hello"
    ]
    actual_after_1 = [h.holders[3].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_type_return(holder):
    sql = """
    CREATE TYPE person AS (name1 TEXT, age1 INT);
    CREATE FUNCTION hello (text) RETURNS person AS $$
        SELECT ROW('Bob', 75)::person;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR, age INT);
    INSERT INTO target (name, age) SELECT * FROM hello('John');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type.this == exp.DataType.Type.USERDEFINED
    assert query.return_type.args["kind"].this == "person"
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("name1"), kind=exp.DataType.build("TEXT")),
        exp.ColumnDef(this=exp.to_identifier("age1"), kind=exp.DataType.build("INT")),
    ]
    assert query.language == "sql"

    assert sorted(h.paths) == [
        ['literal["Bob"]', "column[hello.name1]", "column[target.name]"],
        ["literal[75]", "column[hello.age1]", "column[target.age]"],
    ]

    insert_query_1 = h.holders[3]
    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name1 AS name, hello.age1 AS age FROM (SELECT 'Bob' AS name1, 75 AS age1) AS hello"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_table_return(holder):
    sql = """
    CREATE TABLE people(name VARCHAR, age INT);

    CREATE FUNCTION hello() RETURNS people AS $$
        SELECT ROW('Mary', 25)::people;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR, age INT);
    INSERT INTO target (name, age) SELECT * FROM hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type.this == exp.DataType.Type.USERDEFINED
    assert query.return_type.args["kind"].sql(dialect=DIALECT) == "people"
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("name"), kind=exp.DataType.build("VARCHAR")),
        exp.ColumnDef(this=exp.to_identifier("age"), kind=exp.DataType.build("INT")),
    ]
    assert query.language == "sql"

    assert sorted(h.paths) == [
        ['literal["Mary"]', "column[hello.name]", "column[target.name]"],
        ["literal[25]", "column[hello.age]", "column[target.age]"],
    ]

    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name AS name, hello.age AS age FROM (SELECT 'Mary' AS name, 25 AS age) AS hello"
    ]
    actual_after_1 = [h.holders[3].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_schema_table_return(holder):
    sql = """
    CREATE TABLE earth.people(name VARCHAR, age INT);

    CREATE FUNCTION hello() RETURNS earth.people AS $$
        SELECT ROW('Mary', 25)::earth.people;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name VARCHAR, age INT);
    INSERT INTO target (name, age) SELECT * FROM hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type.this == exp.DataType.Type.USERDEFINED
    assert query.return_type.args["kind"].sql(dialect=DIALECT) == "earth.people"
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("name"), kind=exp.DataType.build("VARCHAR", dialect=DIALECT)),
        exp.ColumnDef(this=exp.to_identifier("age"), kind=exp.DataType.build("INT", dialect=DIALECT)),
    ]
    assert query.language == "sql"

    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name AS name, hello.age AS age FROM (SELECT 'Mary' AS name, 25 AS age) AS hello"
    ]
    actual_after_1 = [h.holders[3].transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1
