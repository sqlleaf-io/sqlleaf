import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "mysql"


def test_ctas_basic(holder):
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


@pytest.mark.skip(reason="todo")
def test_ctas_appended_column(holder):
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


def test_ctas_table_unsupported(holder):
    sql = """
    CREATE TABLE t1 TABLE t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


def test_ctas_with_columns(holder):
    sql = """
    CREATE TABLE t1 (id INT, name VARCHAR) SELECT 1, 'Alice';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE t1 (id INT, name TEXT) AS SELECT 1 AS id, 'Alice' AS name"
    )


def test_ctas_select(holder):
    sql = """
    CREATE TABLE t1 SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert h.queries_transformed[0].statement.sql(dialect="mysql") == "CREATE TABLE t1 AS SELECT 1 AS `1`"


def test_ctas_from_values(holder):
    sql = """
    CREATE TABLE t1 VALUES ROW(1,2), ROW(3,4);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.queries_original[0].KIND == "ctas"
    assert (
        h.queries_transformed[0].statement.sql(dialect="mysql")
        == "CREATE TABLE t1 AS SELECT 1 AS column_0, 2 AS column_1 UNION ALL SELECT 3 AS column_0, 4 AS column_1"
    )


def test_ctas_ignore_unsupported(holder):
    sql = """
    CREATE TABLE t1 IGNORE SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1


def test_ctas_replace_unsupported(holder):
    sql = """
    CREATE TABLE t1 REPLACE SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
