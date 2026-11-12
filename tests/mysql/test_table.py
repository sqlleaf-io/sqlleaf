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
