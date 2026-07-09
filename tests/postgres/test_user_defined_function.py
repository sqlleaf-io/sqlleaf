import os
import sys
import typing as t

import pytest
import sqlglot
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

    assert h.paths == [["udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_schema_udf(holder):
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

    assert h.paths == [["udf[GREETINGS.HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_schema_distinction_udf(holder):
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

    assert sorted(h.paths) == sorted([
        ["udf[HELLO]", "column[target.age]"],
        ["udf[GREETINGS.HELLO]", "column[target.age]"],
    ])

    h.holders[3]
    assert to_sql([h.holders[3].substituted.statement]) == [
        "INSERT INTO target (age) SELECT (SELECT 'no_schema') AS age"
    ]

    h.holders[4]
    assert to_sql([h.holders[4].substituted.statement]) == [
        "INSERT INTO target (age) SELECT (SELECT 'yes_schema') AS age"
    ]


def test_hello_select_udf(holder):
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

    assert h.paths == [["udf[HELLO]", "column[target.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_nested_invocation_udf(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        SELECT 'Hello ' || username;
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello(hello('There'));
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["There"]', "udf[HELLO]", "udf[HELLO]", "column[target.age]"]]

    insert_query = h.holders[2]
    # expect: INSERT INTO target (age) SELECT (SELECT 'Hello ' || (SELECT 'Hello ' || 'There'))
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 'Hello ' || (SELECT 'Hello ' || 'There')) AS age"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_udf_referencing_another_udf(holder):
    sql = """
    CREATE FUNCTION goodbye(username TEXT) RETURNS TEXT AS $$
        SELECT my_unknown(username);
    $$ LANGUAGE sql;

    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT goodbye('Hello');
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    udf_goodbye = h.holders[0].original
    assert isinstance(udf_goodbye, UserDefinedFunctionQuery)
    assert udf_goodbye.function_name == "goodbye"

    udf_hello = h.holders[1].original
    assert isinstance(udf_hello, UserDefinedFunctionQuery)
    assert udf_hello.function_name == "hello"

    assert h.paths == [["udf[HELLO]", "column[target.age]"]]

    h.holders[3]
    # expect: INSERT INTO target (age) SELECT (SELECT (SELECT MY_UNKNOWN('Hello'))) AS age
    insert_after = ["INSERT INTO target (age) SELECT (SELECT (SELECT MY_UNKNOWN('Hello'))) AS age"]

    actual_after = [h.holders[3].substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_void_return_udf(holder):
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

    assert h.paths == [["udf[HELLO]", "column[target.age]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (age) SELECT (SELECT NULL) AS age"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_return_parameter_udf(holder):
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
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 'World') AS age"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_params_udf(holder):
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
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'world') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_positional_params_udf(holder):
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
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || COALESCE('world', 'Guest')) AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_inout_params_udf(holder):
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
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'world') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


def test_hello_default_params_udf(holder):
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
    insert_after = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'World') AS name"]

    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after

    h.holders[3]
    insert_after_2 = ["INSERT INTO target (name) SELECT (SELECT 'Hello ' || 'There') AS name"]

    actual_after = [h.holders[3].substituted.statement]
    assert to_sql(actual_after) == insert_after_2


# If a function returns more than one column, ensure that its 'returned column names' are the name of the parameter (if provided)
# or 'column<N>' if no name is provided, where N is the position of the parameter in the function's list.


def test_hello_inout_parameter_udf(holder):
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
        "INSERT INTO target (msg, bye) SELECT hello.username AS msg, hello.column2 AS bye FROM (SELECT 'Hi' || ' ' || 'User', 'Goodbye ' || 'User') AS hello(username, column2)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_in_out_inout_parameters_udf(holder):
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
        "INSERT INTO target (name1, name2) SELECT hello.middle_name AS name1, hello.last_name AS name2 FROM (SELECT UPPER('There'), LOWER('Hello')) AS hello(middle_name, last_name)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_table_no_params_udf(holder):
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
        "INSERT INTO target (name1, name2) SELECT hello.property AS name1, hello.value AS name2 FROM (SELECT 'prop', 'val') AS hello(property, value)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_multi_statement_params_udf(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        SELECT username;
        SELECT 'Hello ' || username;
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello('Alice');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["Alice"]', "udf[HELLO]", "column[target.age]"]]

    insert_query_1 = h.holders[2]
    insert_after_1 = ["INSERT INTO target (age) SELECT (SELECT 'Hello ' || 'Alice') AS age"]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_cte_udf(holder):
    sql = """
    CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        WITH cte AS (
            SELECT 'Hello ' || username AS msg
        )
        SELECT msg FROM cte;
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello('Alice');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert h.paths == [['literal["Alice"]', "udf[HELLO]", "column[target.age]"]]

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (age) SELECT (WITH cte AS (SELECT 'Hello ' || 'Alice' AS msg) SELECT msg FROM cte) AS age"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_table_and_values_udf(holder):
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
        "INSERT INTO target (name1, name2, age) SELECT hello.property AS name1, hello.value AS name2, 1 AS age FROM (VALUES ('greeting', 'Hello ' || 'John')) AS hello(property, value)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_table_parameter_udf(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE FUNCTION hello(people) RETURNS integer AS $$
        SELECT $1.age * 2 AS age;
    $$ LANGUAGE SQL;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello(people) FROM people;
    INSERT INTO target (age) SELECT hello(people.*) FROM people;
    INSERT INTO target (age) SELECT hello(people) AS double_people FROM people;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.parameters[0].type.this == exp.DataType.Type.USERDEFINED
    assert query.parameters[0].type.args.get("kind").this == "people"

    assert sorted(h.paths) == [
        # TODO: bug. It should be 'age', not star
        ["column[people.*]", "udf[HELLO]", "column[target.age]"],
        ["column[people.age]", "udf[HELLO]", "column[target.age]"],
        ["column[people.age]", "udf[HELLO]", "column[target.age]"],
    ]

    insert_after = ["INSERT INTO target (age) SELECT (SELECT people.age * 2 AS age) AS age FROM people AS people"]

    insert_query_1 = h.holders[3]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after

    insert_query_2 = h.holders[4]
    actual_after_2 = [insert_query_2.substituted.statement]
    assert to_sql(actual_after_2) == insert_after

    insert_query_alias = h.holders[5]
    actual_after_alias = [insert_query_alias.substituted.statement]
    assert to_sql(actual_after_alias) == insert_after


def test_hello_row_parameter_udf(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE FUNCTION hello(people) RETURNS integer AS $$
        SELECT $1.age * 2 AS age;
    $$ LANGUAGE SQL;

    CREATE TABLE target(age INT);
    -- one row
    INSERT INTO target (age) SELECT hello(row(2));
    -- N rows
    INSERT INTO target (age) SELECT hello(row(2)) FROM people;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.parameters[0].type.this == exp.DataType.Type.USERDEFINED
    assert query.parameters[0].type.args.get("kind").this == "people"

    # assert sorted(h.paths) == [
    #     # TODO: bug. It should be 'age', not star
    #     ['column[people.*]', 'udf[HELLO]', 'column[target.age]'],
    #     ['column[people.age]', 'udf[HELLO]', 'column[target.age]'],
    #     ['column[people.age]', 'udf[HELLO]', 'column[target.age]'],
    # ]

    insert_after = ["INSERT INTO target (age) SELECT (SELECT (CAST(ROW(2) AS people)).age * 2 AS age) AS age"]

    h.holders[3]
    actual_after_1 = [h.holders[3].substituted.statement]
    assert to_sql(actual_after_1) == insert_after

    insert_after_from = [
        "INSERT INTO target (age) SELECT (SELECT (CAST(ROW(2) AS people)).age * 2 AS age) AS age FROM people AS people"
    ]

    h.holders[4]
    actual_after_from = [h.holders[4].substituted.statement]
    assert to_sql(actual_after_from) == insert_after_from


# # TODO: return to this one once the basic LATERAL case has been handled in test_select.py
# def test_lateral_udf(holder):
#     sql = """
#     CREATE FUNCTION hello() RETURNS TABLE(property TEXT, value TEXT) AS $$
#         SELECT 'prop', 'val';
#     $$ LANGUAGE sql;
#
#     CREATE TABLE target(name1 VARCHAR, name2 VARCHAR, name3 VARCHAR);
#     -- TODO: this query below works, but reduce it into smaller queries as sibling tests as well
#     INSERT INTO target (name1, name2, name3) SELECT * FROM (SELECT 'goodbye' AS bye) AS bye CROSS JOIN LATERAL hello() as hello(property, value);
#     -- sibling 1
#     -- sibling 2
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     query = h.holders[1].original
#     assert isinstance(query, UserDefinedFunctionQuery)
#
#     assert query.function_name == "hello"
#     assert query.schema_name is None
#     assert query.return_type.this == exp.DataType.Type.USERDEFINED
#     assert query.return_type.args["kind"].this == "person"
#     assert query.return_columns == [
#         exp.ColumnDef(this=exp.to_identifier("name1"), kind=exp.DataType.build("TEXT")),
#         exp.ColumnDef(this=exp.to_identifier("age1"), kind=exp.DataType.build("INT")),
#     ]
#     assert query.language == "sql"
#
#     assert sorted(h.paths) == sorted([
#         ['column[hello.name1]', 'column[target.name]'],
#         ['column[hello.age1]', 'column[target.age]'],
#         ['column[hello.name1]', 'column[target.name]'],
#         ['column[hello.age1]', 'column[target.age]']
#     ])
#
#     # SELECT * FROM (SELECT 'goodbye' AS bye) CROSS JOIN LATERAL (SELECT * FROM (SELECT 'prop', 'val') AS _t1(property, value)) AS _t2(property, value)
#     insert_query_1 = h.holders[3]
#     insert_after_1 = ["INSERT INTO target (name1, name2, name3) SELECT name1, name2, name3 FROM (SELECT 'goodbye' AS bye) AS bye CROSS JOIN LATERAL udf() as udf(property, value)"]
#     actual_after_1 = [h.holders[3].substituted.statement]
#     assert to_sql(actual_after_1) == insert_after_1


def test_hello_composite_type_udf(holder):
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

    assert sorted(h.paths) == sorted([
        ["column[hello.name1]", "column[target.name]"],
        ["column[hello.age1]", "column[target.age]"],
        ["column[hello.name1]", "column[target.name]"],
        ["column[hello.age1]", "column[target.age]"],
    ])

    h.holders[3]
    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name1 AS name, hello.age1 AS age FROM (SELECT 'John', 50) AS hello(name1, age1)"
    ]
    actual_after_1 = [h.holders[3].substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_table_return_udf(holder):
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

    assert sorted(h.paths) == sorted([
        ["column[hello.name]", "column[target.name]"],
        ["column[hello.age]", "column[target.age]"],
        ["column[hello.name]", "column[target.name]"],
        ["column[hello.age]", "column[target.age]"],
    ])

    h.holders[3]
    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name AS name, hello.age AS age FROM (SELECT 'Mary', 25) AS hello(name, age)"
    ]
    actual_after_1 = [h.holders[3].substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_schema_table_return_udf(holder):
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

    h.holders[3]
    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name AS name, hello.age AS age FROM (SELECT 'Mary', 25) AS hello(name, age)"
    ]
    actual_after_1 = [h.holders[3].substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_variadic_parameter_udf(holder):
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
        "INSERT INTO target (name1) SELECT (SELECT 'Hi' || ' ' || STRING_AGG(unpacked_name, ' and ') FROM UNNEST(ARRAY['Alice', 'Bob', 'Charlie']) AS unpacked_name) AS name1"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_mleast_variadic_parameter_udf(holder):
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
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[i]) FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1

    insert_query_2 = h.holders[3]
    insert_after_2 = [
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[i]) FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after_2 = [insert_query_2.substituted.statement]
    assert to_sql(actual_after_2) == insert_after_2

    insert_query_3 = h.holders[4]
    insert_after_3 = [
        "INSERT INTO target (age) SELECT (SELECT MIN((CAST(ARRAY[] AS DECIMAL[]))[i]) FROM GENERATE_SUBSCRIPTS(CAST(ARRAY[] AS DECIMAL[]), 1) AS g(i)) AS age"
    ]
    actual_after_3 = [insert_query_3.substituted.statement]
    assert to_sql(actual_after_3) == insert_after_3

    insert_query_4 = h.holders[5]
    insert_after_4 = [
        "INSERT INTO target (age) WITH data_source AS (SELECT CAST(ARRAY[10, -1, 5, 4.4] AS DECIMAL[]) AS my_array) SELECT (SELECT MIN(data_source.my_array[i]) FROM GENERATE_SUBSCRIPTS(data_source.my_array, 1) AS g(i)) AS age FROM data_source AS data_source"
    ]
    actual_after_4 = [insert_query_4.substituted.statement]
    assert to_sql(actual_after_4) == insert_after_4


def test_hello_overloading_udf(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TEXT AS $$
        SELECT 'Hello';
    $$ LANGUAGE sql;

    CREATE FUNCTION hello(text) RETURNS TEXT AS $$
        SELECT 'Hello TEXT';
    $$ LANGUAGE sql;

    CREATE FUNCTION hello(int) RETURNS TEXT AS $$
        SELECT 'Hello INT';
    $$ LANGUAGE sql;

    CREATE FUNCTION hello(double) RETURNS TEXT AS $$
        SELECT 'Hello DOUBLE';
    $$ LANGUAGE sql;

    CREATE FUNCTION hello(text, text) RETURNS TEXT AS $$
        SELECT 'Hello TEXT, TEXT';
    $$ LANGUAGE sql;

    CREATE TABLE target(name1 VARCHAR);

    INSERT INTO target (name1) SELECT hello();
    INSERT INTO target (name1) SELECT hello(42);
    INSERT INTO target (name1) SELECT hello('World');
    INSERT INTO target (name1) SELECT hello(1.5);
    INSERT INTO target (name1) SELECT hello('a', 'b');
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    insert_query_1 = h.holders[6]
    insert_after_1 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello') AS name1"]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1

    insert_query_2 = h.holders[7]
    insert_after_2 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello INT') AS name1"]
    actual_after_2 = [insert_query_2.substituted.statement]
    assert to_sql(actual_after_2) == insert_after_2

    insert_query_3 = h.holders[8]
    insert_after_3 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello TEXT') AS name1"]
    actual_after_3 = [insert_query_3.substituted.statement]
    assert to_sql(actual_after_3) == insert_after_3

    insert_query_4 = h.holders[9]
    insert_after_4 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello DOUBLE') AS name1"]
    actual_after_4 = [insert_query_4.substituted.statement]
    assert to_sql(actual_after_4) == insert_after_4

    insert_query_5 = h.holders[10]
    insert_after_5 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello TEXT, TEXT') AS name1"]
    actual_after_5 = [insert_query_5.substituted.statement]
    assert to_sql(actual_after_5) == insert_after_5


def test_hello_table_join_same_table_udf(holder):
    sql = """
    CREATE FUNCTION hello() RETURNS TABLE(property TEXT, value TEXT) AS $$
        SELECT 'prop', 'val';
    $$ LANGUAGE SQL;

    CREATE TABLE target(name1 VARCHAR, name2 VARCHAR, name3 VARCHAR, name4 VARCHAR);
    INSERT INTO target (name1, name2, name3, name4) SELECT * FROM hello() h, hello() i;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_type.this == exp.DataType.Type.USERDEFINED
    assert query.return_columns == [
        exp.ColumnDef(this=exp.to_identifier("property"), kind=exp.DType.TEXT.into_expr()),
        exp.ColumnDef(this=exp.to_identifier("value"), kind=exp.DType.TEXT.into_expr()),
    ]
    assert query.language == "sql"

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (name1, name2, name3, name4) SELECT h.property AS name1, h.value AS name2, i.property AS name3, i.value AS name4 FROM (SELECT 'prop', 'val') AS h(property, value) CROSS JOIN (SELECT 'prop', 'val') AS i(property, value)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_type_return_udf(holder):
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

    assert sorted(h.paths) == sorted([
        ["column[hello.name1]", "column[target.name]"],
        ["column[hello.age1]", "column[target.age]"],
        ["column[hello.name1]", "column[target.name]"],
        ["column[hello.age1]", "column[target.age]"],
    ])

    insert_query_1 = h.holders[3]
    insert_after_1 = [
        "INSERT INTO target (name, age) SELECT hello.name1 AS name, hello.age1 AS age FROM (SELECT 'Bob', 75) AS hello(name1, age1)"
    ]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_parameter_column_precedence_udf(holder):
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
    insert_after_1 = ["INSERT INTO target (name) SELECT (SELECT name FROM people) AS name"]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_any_type_fallback_udf(holder):
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
    insert_after_1 = ["INSERT INTO target (age) SELECT (SELECT 2) AS age"]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


# TODO: these skip the execution of the inner queries completely; do not include in lineage
cases = ["STRICT", "RETURNS NULL ON NULL INPUT"]


@pytest.mark.parametrize("case", cases)
def test_hello_null_on_null_input_udf(holder, case: str):
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
    insert_after_1 = ["INSERT INTO target (age) SELECT (SELECT NULL) AS age"]
    actual_after_1 = [insert_query_1.substituted.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test_hello_insert_returning_udf(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE OR REPLACE FUNCTION hello() RETURNS INT AS $$
        INSERT INTO people (age) VALUES (5), (2) RETURNING age;
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    insert_query = h.holders[3]
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 5) AS age"]
    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after


# The same as above, but just a SELECT.
# TODO: this will work once the logic to process UDFs in any place
#  make the query segment valid (e.g. in WHERE cluases)
# def test_hello_select_insert_returning_udf(holder):
#     sql = """
#     CREATE TABLE people(age INT);
#
#     CREATE OR REPLACE FUNCTION hello() RETURNS INT AS $$
#         INSERT INTO people (age) VALUES (5), (2) RETURNING age;
#     $$ LANGUAGE sql;
#
#     CREATE TABLE target(age INT);
#     SELECT hello();
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     query = h.holders[1].original
#     assert isinstance(query, UserDefinedFunctionQuery)
#
#     insert_query = h.holders[3]
#     insert_after = ["INSERT INTO target (age) SELECT (SELECT 5) AS age"]
#     actual_after = [insert_query.substituted.statement]
#     assert to_sql(actual_after) == insert_after


def test_hello_delete_returning_positional_udf(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE OR REPLACE FUNCTION hello(int) RETURNS INT AS $$
        DELETE FROM people RETURNING $1;
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target SELECT hello(6);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    insert_query = h.holders[3]
    insert_after_2 = ["INSERT INTO target (age) SELECT (SELECT 6) AS age"]
    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after_2


def test_hello_merge_returning_udf(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE OR REPLACE FUNCTION hello(text) RETURNS TEXT AS $$
        MERGE INTO target AS t
        USING people AS s
        ON t.age = s.age
        WHEN MATCHED THEN
            UPDATE SET age = s.age
        RETURNING merge_action();
    $$ LANGUAGE sql;

    CREATE TABLE target(age INT);
    INSERT INTO target SELECT hello(6);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    insert_query = h.holders[3]
    # This is technically invalid as merge_action() can only be used inside a MERGE,
    # but we do this anyway for lineage purposes.
    insert_after_2 = ["INSERT INTO target (age) SELECT (SELECT MERGE_ACTION()) AS age"]
    actual_after = [insert_query.substituted.statement]
    assert to_sql(actual_after) == insert_after_2


# TODO: inner schema call
"""
CREATE FUNCTION hello(username TEXT) RETURNS TEXT AS $$
        SELECT my.unknown(username);
    $$ LANGUAGE sql;
"""
