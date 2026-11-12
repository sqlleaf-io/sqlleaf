import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__load_data_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        LOAD DATA INFILE 'data.txt' INTO TABLE db2.my_table;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__load_data_set_expression_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        LOAD DATA INFILE 'file.txt'
          INTO TABLE t1
          (column1, @var1)
          SET column2 = @var1/100;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")


def test__load_data_set_current_timestamp_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        LOAD DATA INFILE 'file.txt'
          INTO TABLE t1
          (column1, column2)
          SET column3 = CURRENT_TIMESTAMP;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")
