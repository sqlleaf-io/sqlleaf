import os
import sys

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


def test__ctas_appended_column(holder):
    sql = """
    CREATE TABLE bar (m INT) SELECT 2 as n;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["null[NULL]", "column[bar.m]"],
        ["literal[2]", "column[bar.n]"],
    ]
    assert "column[name=n type=INT properties=[kind=table table=bar]]" in h.nodes_full
    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE bar (m INT) AS SELECT NULL AS m, 2 AS n"
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
        == "CREATE TABLE t1 (id INT, name TEXT) AS SELECT NULL AS id, NULL AS name, 1 AS `1`, 'Alice' AS Alice"
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
    assert h.paths == [
        ["null[NULL]", "column[target.x]"],
        ["column[source.n]", "column[target.n]"],
    ]


def test__ctas_values_default_column_names(holder):
    sql = """
    CREATE TABLE tv1 VALUES ROW(1,3,5), ROW(2,4,6);
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


def test__ctas_table_with_columns_appended(holder):
    sql = """
    CREATE TABLE t1 (a INT, b INT);
    CREATE TABLE t2 (x INT) TABLE t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[1].KIND == "ctas"
    assert (
        h.queries_transformed[1].statement.sql(dialect=DIALECT)
        == "CREATE TABLE t2 (x INT) AS SELECT NULL AS x, t1.a AS a, t1.b AS b FROM t1 AS t1"
    )
    assert h.paths == [
        ["null[NULL]", "column[t2.x]"],
        ["column[t1.a]", "column[t2.a]"],
        ["column[t1.b]", "column[t2.b]"],
    ]


def test__ctas_table_with_columns_from_values_alias(holder):
    sql = """
    CREATE TABLE t1 (a INT, b INT, c INT) SELECT * FROM (VALUES ROW(1,3,5), ROW(2,4,6)) AS v(a,b,c);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "CREATE TABLE t1 (a INT, b INT, c INT) AS SELECT v.a AS a, v.b AS b, v.c AS c FROM (SELECT 1 AS a, 3 AS b, 5 AS c UNION ALL SELECT 2 AS a, 4 AS b, 6 AS c) AS v"
    )
    assert h.paths == [
        ["literal[1]", "column[v.a]", "column[t1.a]"],
        ["literal[2]", "column[v.a]", "column[t1.a]"],
        ["literal[3]", "column[v.b]", "column[t1.b]"],
        ["literal[4]", "column[v.b]", "column[t1.b]"],
        ["literal[5]", "column[v.c]", "column[t1.c]"],
        ["literal[6]", "column[v.c]", "column[t1.c]"],
    ]


def test__ctas_table_with_columns_from_values_alias_mismatch(holder):
    sql = """
    CREATE TABLE t1 (a INT, b INT, c INT) SELECT * FROM (VALUES ROW(1,3,5), ROW(2,4,6)) AS v(x,y,z);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect=DIALECT)
        == "CREATE TABLE t1 (a INT, b INT, c INT) AS SELECT NULL AS a, NULL AS b, NULL AS c, v.x AS x, v.y AS y, v.z AS z FROM (SELECT 1 AS x, 3 AS y, 5 AS z UNION ALL SELECT 2 AS x, 4 AS y, 6 AS z) AS v"
    )
    assert h.paths == [
        ["null[NULL]", "column[t1.a]"],
        ["null[NULL]", "column[t1.b]"],
        ["null[NULL]", "column[t1.c]"],
        ["literal[1]", "column[v.x]", "column[t1.x]"],
        ["literal[2]", "column[v.x]", "column[t1.x]"],
        ["literal[3]", "column[v.y]", "column[t1.y]"],
        ["literal[4]", "column[v.y]", "column[t1.y]"],
        ["literal[5]", "column[v.z]", "column[t1.z]"],
        ["literal[6]", "column[v.z]", "column[t1.z]"],
    ]
