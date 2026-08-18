import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test__to_query_named_argument(holder):
    sql = """
    CREATE TABLE source (age INT, name TEXT);
    CREATE TABLE target (age INT, name TEXT);

    INSERT INTO target
    SELECT * FROM TABLE(TO_QUERY(SQL => 'SELECT * FROM source'));
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[2].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO TARGET (AGE, NAME) SELECT SOURCE.AGE AS AGE, SOURCE.NAME AS NAME FROM SOURCE AS SOURCE"
    )
    assert h.paths == [
        ["column[SOURCE.AGE]", "column[TARGET.AGE]"],
        ["column[SOURCE.NAME]", "column[TARGET.NAME]"],
    ]


def test__to_query_positional_argument(holder):
    sql = """
    CREATE TABLE source (age INT, name TEXT);
    CREATE TABLE target (age INT, name TEXT);

    INSERT INTO target
    SELECT * FROM TABLE(TO_QUERY('SELECT * FROM source'));
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[2].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO TARGET (AGE, NAME) SELECT SOURCE.AGE AS AGE, SOURCE.NAME AS NAME FROM SOURCE AS SOURCE"
    )
    assert h.paths == [
        ["column[SOURCE.AGE]", "column[TARGET.AGE]"],
        ["column[SOURCE.NAME]", "column[TARGET.NAME]"],
    ]


def test__to_query_parameterized_bind_variables(holder):
    sql = """
    CREATE TABLE source (age INT, name TEXT);
    CREATE TABLE target (age INT, name TEXT);

    INSERT INTO target
    SELECT * FROM TABLE(TO_QUERY(SQL => 'SELECT * FROM source WHERE age = ?', 10));
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[2].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO TARGET (AGE, NAME) SELECT SOURCE.AGE AS AGE, SOURCE.NAME AS NAME FROM SOURCE AS SOURCE"
    )
    assert h.paths == [["column[SOURCE.AGE]", "column[TARGET.AGE]"], ["column[SOURCE.NAME]", "column[TARGET.NAME]"]]


def test__to_query_numeric_bind_variables(holder):
    sql = """
    CREATE TABLE source (age INT, name TEXT);
    CREATE TABLE target (age INT, name TEXT);

    INSERT INTO target
    SELECT * FROM TABLE(TO_QUERY(SQL => 'SELECT * FROM source WHERE id = :1', 10));
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[2].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO TARGET (AGE, NAME) SELECT SOURCE.AGE AS AGE, SOURCE.NAME AS NAME FROM SOURCE AS SOURCE"
    )
    assert h.paths == [["column[SOURCE.AGE]", "column[TARGET.AGE]"], ["column[SOURCE.NAME]", "column[TARGET.NAME]"]]


#
# def test__to_query_session_variable(holder):
#     with pytest.raises(SqlLeafException):
#         sql = """
#         CREATE TABLE source (age INT, name TEXT);
#         CREATE TABLE target (age INT, name TEXT);
#
#         INSERT INTO target
#         SELECT * FROM TABLE(TO_QUERY(SQL => $sql_session_var));
#         """
#         holder(sql=sql, dialect=DIALECT)

#
# def test__to_query_identifier_with_set_variable(holder):
#     sql = """
#     CREATE TABLE source (age INT, name TEXT);
#     CREATE TABLE target (age INT, name TEXT);
#
#     SET table_name = 'source';
#
#     INSERT INTO target
#     SELECT * FROM TABLE(TO_QUERY('SELECT * FROM IDENTIFIER($table_name)'));
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     assert h.paths == [
#         ["column[SOURCE.AGE]", "column[TARGET.AGE]"],
#         ["column[SOURCE.NAME]", "column[TARGET.NAME]"],
#     ]


# def test__to_query_identifier_with_missing_variable(holder):
#     with pytest.raises(SqlLeafException):
#         sql = """
#         CREATE TABLE target (age INT, name TEXT);
#
#         INSERT INTO target
#         SELECT * FROM TABLE(TO_QUERY('SELECT * FROM IDENTIFIER($undefined_var)'));
#         """
#         holder(sql=sql, dialect=DIALECT)
