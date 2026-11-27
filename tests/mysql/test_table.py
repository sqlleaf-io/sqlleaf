import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


# TODO: generated columns
# CREATE TABLE triangle (
#   sidea DOUBLE,
#   sideb DOUBLE,
#   sidec DOUBLE AS (SQRT(sidea * sidea + sideb * sideb))
# );


def test__table_like_table(holder):
    sql = """
    CREATE TABLE source (id INT, n INT, name VARCHAR(10));
    CREATE TABLE target LIKE source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.queries_transformed[1].statement.sql(dialect=DIALECT) == "CREATE TABLE target LIKE source"


def test__table_inline_index_enum_set_select(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        CREATE TABLE source (id INT, n INT);
        CREATE TABLE target (id INT AUTO_INCREMENT PRIMARY KEY, v INT ZEROFILL UNSIGNED, e ENUM('a','b'), s SET('x','y'), INDEX ix (v)) SELECT n AS v FROM source;
        """
        holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0].startswith("Expecting ). Line 3, Col: 87.")


def test__table_into_dumpfile_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        TABLE t1 INTO DUMPFILE 'file.txt';
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__table_into_outfile_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        TABLE t1 INTO OUTFILE 'file.txt';
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__table_into_var_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        TABLE t1 INTO @var1, @var2;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__table_paren(holder):
    sql = """
    CREATE TABLE t (a INT, b INT);
    (TABLE t);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_transformed[1].statement.sql(dialect=DIALECT) == "SELECT t.a AS a, t.b AS b FROM t AS t"


def test__table_invisible_column_not_selected_by_star(holder):
    sql = """
    CREATE TABLE source (id INT, secret INT INVISIBLE, name VARCHAR(10));
    CREATE TABLE target (id INT, name VARCHAR(10));
    INSERT INTO target SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.queries_transformed[2].statement.sql(dialect=DIALECT)
        == "INSERT INTO target (id, name) SELECT source.id AS id, source.name AS name FROM source AS source"
    )
    assert h.paths == [
        ["column[source.id]", "column[target.id]"],
        ["column[source.name]", "column[target.name]"],
    ]


def test__table_invisible_column_named_explicitly(holder):
    sql = """
        CREATE TABLE source (id INT, secret INT INVISIBLE, name VARCHAR(10));
        CREATE TABLE target (id INT, name VARCHAR(10));
        INSERT INTO target (name) SELECT secret FROM source;
        """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.queries_transformed[2].statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT source.secret AS name FROM source AS source"
    )
    assert h.paths == [["column[source.secret]", "column[target.name]"]]


def test__table_invisible_column_named_insert_target(holder):
    sql = """
        CREATE TABLE source (id INT, secret INT INVISIBLE, name VARCHAR(10));
        INSERT INTO source (id, secret, name) SELECT 1, 2, 'a';
        """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[1]", "column[source.id]"],
        ['literal["a"]', "column[source.name]"],
        ["literal[2]", "column[source.secret]"],
    ]


def test__table_like_copies_invisible_column(holder):
    sql = """
        CREATE TABLE source (id INT, secret INT INVISIBLE, name VARCHAR(10));
        CREATE TABLE target (LIKE source);
        INSERT INTO target (secret) SELECT id FROM source;
        """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.id]", "column[target.secret]"]]


# TODO: SET SESSION sql_generate_invisible_primary_key=ON to make 'CREATE TABLE' add a column 'my_row_id'
