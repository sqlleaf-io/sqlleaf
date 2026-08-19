import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__values_empty_insert(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255), age INT DEFAULT 5);
    INSERT INTO target () VALUES();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name, age) SELECT NULL AS name, 5 AS age"
    )


def test__values_empty_insert_named_columns(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255), age INT DEFAULT 5);
    INSERT INTO target (name, age) VALUES(name, age);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name, age) SELECT NULL AS name, 5 AS age"
    )


def test__values_empty_insert_named_columns_with_functions(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255), age INT DEFAULT 5);
    INSERT INTO target (name, age) VALUES(UPPER(name), age*2);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name, age) SELECT UPPER(NULL) AS name, 10 AS age"
    )
