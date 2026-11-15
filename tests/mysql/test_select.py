import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__select_into_outfile_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        SELECT * INTO OUTFILE 'data.txt'
          FIELDS TERMINATED BY ','
          FROM table2;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__select_into_variable(holder):
    sql = """
    SELECT name INTO @n FROM test_source WHERE name = 'Alice';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.lineage.object_mapping.variables.get_variable("n").sql(dialect=DIALECT) == "test_source.name"


def test__select_into_variable_expression(holder):
    sql = """
    SELECT UPPER(name) INTO @x FROM test_source;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.lineage.object_mapping.variables.get_variable("x").sql(dialect=DIALECT) == "UPPER(test_source.name)"


def test__select_into_multiple_variables(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        SELECT name, kind INTO @n, @k FROM fruit.raw WHERE age > 1;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__select_into_variable_after_limit(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        SELECT name FROM test_source LIMIT 1 INTO @n;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__select_paren(holder):
    sql = """
    (SELECT a FROM t);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_transformed[0].statement.sql(dialect=DIALECT) == "SELECT a AS a FROM t AS t"


def test__union_paren(holder):
    sql = """
    (SELECT 1) UNION (SELECT 2);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_transformed[0].statement.sql(dialect=DIALECT) == "SELECT 1 AS `1` UNION SELECT 2 AS `2`"


def test__union_paren_limit(holder):
    sql = """
    CREATE TABLE t1 (a INT);
    CREATE TABLE t2 (b INT);
    (SELECT a FROM t1 LIMIT 5) UNION (SELECT b FROM t2 LIMIT 5);
    """
    h = holder(sql=sql, dialect=DIALECT)

    # Keep the brackets if there's LIMIT or ORDER BY
    assert (
        h.queries_transformed[2].statement.sql(dialect=DIALECT)
        == "(SELECT t1.a AS a FROM t1 AS t1 LIMIT 5) UNION (SELECT t2.b AS b FROM t2 AS t2 LIMIT 5)"
    )


def test__with_paren(holder):
    sql = """
    (WITH c AS (SELECT a FROM t) SELECT a FROM c);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "WITH c AS (SELECT a AS a FROM t AS t) SELECT c.a AS a FROM c AS c"
    )


def test__nested_paren(holder):
    sql = """
    SELECT * FROM ((SELECT a FROM t)) x;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_transformed[0].statement.sql(dialect=DIALECT) == "SELECT a AS a FROM t AS t"
