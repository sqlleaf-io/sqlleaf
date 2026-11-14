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
