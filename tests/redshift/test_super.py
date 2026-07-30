import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "redshift"


def test__super_select_super_column(holder):
    sql = """
    CREATE TABLE source (age INT, data SUPER);
    CREATE TABLE target (col_1 INT, col_2 INT, col_3 DOUBLE);

    INSERT INTO target (col_1, col_2, col_3)
    SELECT
        c.age,
        c.data.name,
        c.data.items[0].address
    FROM source AS c;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.age]", "column[target.col_1]"],
        ["column[source.data]", "column[target.col_2]"],
        ["column[source.data]", "column[target.col_3]"],
    ]


def test__super_insert_into_super_column(holder):
    sql = """
    CREATE TABLE source (age INT, data SUPER);
    CREATE TABLE target (new_data SUPER);

    INSERT INTO target (new_data)
    SELECT s.data FROM source AS s;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.data]", "column[target.new_data]"]]
