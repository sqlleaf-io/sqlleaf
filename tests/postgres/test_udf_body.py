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


def test__udf_cte(holder):
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

    insert_query_1 = h.holders[2]
    insert_after_1 = [
        "INSERT INTO target (age) SELECT (WITH cte AS (SELECT 'Hello Alice' AS msg) SELECT cte.msg AS msg FROM cte AS cte) AS age"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1

    assert h.paths == [['literal["Hello Alice"]', "column[cte.msg]", "column[target.age]"]]


def test__udf_multi_statement_params(holder):
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

    insert_query = h.holders[2]
    insert_after = ["INSERT INTO target (age) SELECT (SELECT 'Hello Alice' AS _col_0) AS age"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello Alice"]', "column[target.age]"]]


def test__udf_nested_invocation(holder):
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

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (age) SELECT (SELECT 'Hello ' || (SELECT 'Hello There' AS _col_0) AS _col_0) AS age"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [
        ['literal["Hello "]', "function[DPIPE]", "column[target.age]"],
        ['literal["Hello There"]', "function[DPIPE]", "column[target.age]"],
    ]


def test__udf_referencing_another(holder):
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

    insert_after = ["INSERT INTO target (age) SELECT (SELECT (SELECT MY_UNKNOWN('Hello') AS _col_0) AS _col_0) AS age"]
    actual_after = [h.holders[3].transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [['literal["Hello"]', "udf[MY_UNKNOWN]", "column[target.age]"]]


def test__udf_overloading(holder):
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
    insert_after_1 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello' AS Hello) AS name1"]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1

    insert_query_2 = h.holders[7]
    insert_after_2 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello INT' AS \"Hello INT\") AS name1"]
    actual_after_2 = [insert_query_2.transformed.statement]
    assert to_sql(actual_after_2) == insert_after_2

    insert_query_3 = h.holders[8]
    insert_after_3 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello TEXT' AS \"Hello TEXT\") AS name1"]
    actual_after_3 = [insert_query_3.transformed.statement]
    assert to_sql(actual_after_3) == insert_after_3

    insert_query_4 = h.holders[9]
    insert_after_4 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello DOUBLE' AS \"Hello DOUBLE\") AS name1"]
    actual_after_4 = [insert_query_4.transformed.statement]
    assert to_sql(actual_after_4) == insert_after_4

    insert_query_5 = h.holders[10]
    insert_after_5 = ["INSERT INTO target (name1) SELECT (SELECT 'Hello TEXT, TEXT' AS \"Hello TEXT, TEXT\") AS name1"]
    actual_after_5 = [insert_query_5.transformed.statement]
    assert to_sql(actual_after_5) == insert_after_5


def test__udf_table_join_same_table(holder):
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
        "INSERT INTO target (name1, name2, name3, name4) SELECT h.property AS name1, h.value AS name2, i.property AS name3, i.value AS name4 FROM (SELECT 'prop' AS property, 'val' AS value) AS h(property, value) CROSS JOIN (SELECT 'prop' AS property, 'val' AS value) AS i(property, value)"
    ]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after_1


def test__udf_table_parameter(holder):
    sql = """
    CREATE TABLE people(age INT);

    CREATE FUNCTION hello(people) RETURNS integer AS $$
        SELECT $1.age * 2 AS age;
    $$ LANGUAGE SQL;

    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT hello(people) FROM people;
    --INSERT INTO target (age) SELECT hello(people.*) FROM people;
    --INSERT INTO target (age) SELECT hello(people) AS double_people FROM people;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.parameters[0].type.this == exp.DataType.Type.USERDEFINED
    assert query.parameters[0].type.args.get("kind").this == "people"

    insert_after = ["INSERT INTO target (age) SELECT (SELECT people.age * 2 AS age) AS age FROM people AS people"]
    insert_query_1 = h.holders[3]
    actual_after_1 = [insert_query_1.transformed.statement]
    assert to_sql(actual_after_1) == insert_after

    # insert_query_2 = h.holders[4]
    # actual_after_2 = [insert_query_2.transformed.statement]
    # assert to_sql(actual_after_2) == insert_after
    #
    # insert_query_alias = h.holders[5]
    # actual_after_alias = [insert_query_alias.transformed.statement]
    # assert to_sql(actual_after_alias) == insert_after

    assert sorted(h.paths) == [
        ["column[people.age]", "function[MUL]", "column[target.age]"],
        ["literal[2]", "function[MUL]", "column[target.age]"],
    ]


def test__udf_row_parameter(holder):
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

    insert_after = ["INSERT INTO target (age) SELECT (SELECT CAST(ROW(2) AS people).age * 2 AS age) AS age"]
    actual_after_1 = [h.holders[3].transformed.statement]
    assert to_sql(actual_after_1) == insert_after

    insert_after_from = [
        "INSERT INTO target (age) SELECT (SELECT CAST(ROW(2) AS people).age * 2 AS age) AS age FROM people AS people"
    ]
    actual_after_from = [h.holders[4].transformed.statement]
    assert to_sql(actual_after_from) == insert_after_from

    assert h.paths == [
        ["literal[2]", "function[MUL]", "column[target.age]"],
        ["literal[2]", "function[MUL]", "column[target.age]"],
    ]


def test__udf_insert_returning(holder):
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
    insert_after = ["INSERT INTO target (age) SELECT (SELECT people.age AS age FROM people AS people) AS age"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after

    assert h.paths == [
        ["literal[5]", "column[people.age]", "column[target.age]"],
        ["literal[2]", "column[people.age]", "column[target.age]"],
    ]


def test__udf_delete_returning_positional(holder):
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
    insert_after_2 = ['INSERT INTO target (age) SELECT (SELECT 6 AS "6") AS age']
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after_2


def test__udf_merge_returning(holder):
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
    insert_after_2 = ["INSERT INTO target (age) SELECT (SELECT MERGE_ACTION() AS _col_0) AS age"]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after) == insert_after_2
