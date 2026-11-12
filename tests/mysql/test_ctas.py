import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "mysql"


def test__ctas_basic(holder):
    sql = """
    CREATE TABLE t2 (name VARCHAR);
    CREATE TABLE t1 SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "column[name=name type=VARCHAR properties=[kind=table table=t1]]",
        "column[name=name type=VARCHAR properties=[kind=table table=t2]]",
    ]
    assert h.paths == [["column[t2.name]", "column[t1.name]"]]
    assert h.queries_original[1].KIND == "ctas"


# mysql> CREATE TABLE tv3 (a INT, b INT, c INT)
#      >     SELECT * FROM (VALUES ROW(1,3,5), ROW(2,4,6)) AS v(x,y,z);
# mysql> TABLE tv3;
# +------+------+------+----------+----------+----------+
# | a    | b    | c    |        x |        y |        z |
# +------+------+------+----------+----------+----------+
# | NULL | NULL | NULL |        1 |        3 |        5 |
# | NULL | NULL | NULL |        2 |        4 |        6 |
# +------+------+------+----------+----------+----------+


# "Notice that the columns from the SELECT statement are appended to the right side of the table, not overlapped onto it."
# CREATE TABLE bar (m INT) SELECT n FROM foo;
# (where n = 1 inside foo)
# +------+---+
# | m    | n |
# +------+---+
# | NULL | 1 |
# +------+---+


@pytest.mark.skip(reason="todo")
def test__ctas_appended_column(holder):
    sql = """
    CREATE TABLE bar (m INT) SELECT 2 as n;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.nodes_full == []
    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE bar (m INT, n INT) AS SELECT NULL AS m, 2 AS n"
    )


def test__ctas_table(holder):
    sql = """
    CREATE TABLE t1 (name VARCHAR, age INT);
    CREATE TABLE t2 TABLE t1;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        h.queries_transformed[1].statement.sql(dialect=DIALECT)
        == "CREATE TABLE t2 AS SELECT t1.name AS name, t1.age AS age FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.name]", "column[t2.name]"],
        ["column[t1.age]", "column[t2.age]"],
    ]


def test__ctas_with_columns(holder):
    sql = """
    CREATE TABLE t1 (id INT, name VARCHAR) SELECT 1, 'Alice';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE t1 (id INT, name TEXT) AS SELECT 1 AS id, 'Alice' AS name"
    )


def test__ctas_select(holder):
    sql = """
    CREATE TABLE t1 SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert h.queries_transformed[0].statement.sql(dialect="mysql") == "CREATE TABLE t1 AS SELECT 1 AS `1`"


def test__ctas_from_values(holder):
    sql = """
    CREATE TABLE t1 VALUES ROW(1,2), ROW(3,4);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE t1 AS SELECT 1 AS column_0, 2 AS column_1 UNION ALL SELECT 3 AS column_0, 4 AS column_1"
    )


def test__ctas_ignore_unsupported(holder):
    sql = """
    CREATE TABLE t1 IGNORE SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


def test__ctas_replace_unsupported(holder):
    sql = """
    CREATE TABLE t1 REPLACE SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


def test__table_as_parenthesized_select(holder):
    sql = """
    CREATE TABLE source (id INT, n INT);
    CREATE TABLE target AS (SELECT n FROM source);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[1].KIND == "ctas"
    assert (
        h.queries_transformed[1].statement.sql(dialect=DIALECT)
        == "CREATE TABLE target AS SELECT source.n AS n FROM source AS source"
    )
    assert h.paths == [["column[source.n]", "column[target.n]"]]


def test__table_as_parenthesized_select_with_columns(holder):
    sql = """
    CREATE TABLE source (id INT, n INT);
    CREATE TABLE target (x INT) AS (SELECT n FROM source);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[1].KIND == "ctas"
    assert h.paths == [["column[source.n]", "column[target.x]"]]


def test__ctas_values_default_column_names(holder):
    sql = """
    CREATE TABLE tv1 VALUES ROW(1,3,5), ROW(2,4,6);
    TABLE tv1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "CREATE TABLE tv1 AS SELECT 1 AS column_0, 3 AS column_1, 5 AS column_2 UNION ALL SELECT 2 AS column_0, 4 AS column_1, 6 AS column_2"
    )
    assert "column[name=column_0 type=INT properties=[kind=table table=tv1]]" in h.nodes_full
    assert "column[name=column_1 type=INT properties=[kind=table table=tv1]]" in h.nodes_full
    assert "column[name=column_2 type=INT properties=[kind=table table=tv1]]" in h.nodes_full
