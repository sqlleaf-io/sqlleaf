import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import InsertQuery, SelectQuery, SetQuery

DIALECT = "snowflake"


def test___set_simple(holder):
    sql = """
    SET a = 10;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["A"].to_py() == 10


def test___set_multiple_variables(holder):
    sql = """
    SET (a, b) = (10, 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["A"].to_py() == 10
    assert h.lineage.object_mapping.session_variables["B"].to_py() == 20


def test___set_multiple_statements(holder):
    sql = """
    SET a = 10;
    SET b = 20;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["A"].to_py() == 10
    assert h.lineage.object_mapping.session_variables["B"].to_py() == 20


def test___set_subquery(holder):
    sql = """
    SET a = (SELECT max(col) FROM my_table);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "SELECT MAX(COL) FROM MY_TABLE" in h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT)


def test___set_multiple_subquery(holder):
    sql = """
    SET (a, b) = (SELECT col1, col2 FROM table LIMIT 1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert "(SELECT COL1 FROM TABLE LIMIT 1)" in h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT)
    assert "(SELECT COL2 FROM TABLE LIMIT 1)" in h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT)


def test___set_variable_composition(holder):
    sql = """
    SET a = 1;
    SET b = $a + 1;
    INSERT INTO fruit.processed (age) SELECT $b;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert [SetQuery, SetQuery, InsertQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT) == "$a + 1"
    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO FRUIT.PROCESSED (AGE) SELECT 2 AS AGE"
    )


def test___variable_substitution_in_select(holder):
    sql = """
    SET a = 'hi';
    CREATE TABLE t AS SELECT $a AS col;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [['literal["hi"]', "column[T.COL]"]]

    actual_sql = h.holders[1].transformed.statement.sql(dialect=DIALECT)
    assert actual_sql == "CREATE TABLE T AS SELECT 'hi' AS COL"


def test___identifier_in_from_clause(holder):
    sql = """
    CREATE TABLE my_table (col1 INT);
    SET b = 'my_table';
    CREATE TABLE t AS SELECT col1 FROM IDENTIFIER($b);
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [["column[MY_TABLE.COL1]", "column[T.COL1]"]]

    actual_sql = h.holders[2].transformed.statement.sql(dialect=DIALECT)
    assert actual_sql == "CREATE TABLE T AS SELECT MY_TABLE.COL1 AS COL1 FROM MY_TABLE AS MY_TABLE"


def test___identifier_in_insert_target(holder):
    sql = """
    CREATE TABLE dest (col INT);
    CREATE TABLE src (col INT);
    SET tbl = 'dest';
    INSERT INTO IDENTIFIER($tbl) SELECT col FROM src;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[SRC.COL]", "column[DEST.COL]"],
    ]
    actual_sql = h.holders[3].transformed.statement.sql(dialect=DIALECT)
    assert actual_sql == "INSERT INTO DEST (COL) SELECT SRC.COL AS COL FROM SRC AS SRC"


def test___identifier_in_select_expression(holder):
    sql = """
    CREATE SCHEMA fruit;
    CREATE TABLE fruit.processed (amount INT);
    SET col_name = 'amount';
    CREATE TABLE t AS SELECT IDENTIFIER($col_name) FROM fruit.processed;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [["column[FRUIT.PROCESSED.AMOUNT]", "column[T.AMOUNT]"]]

    actual_sql = h.holders[2].transformed.statement.sql(dialect=DIALECT)
    assert actual_sql == "CREATE TABLE T AS SELECT PROCESSED.AMOUNT AS AMOUNT FROM FRUIT.PROCESSED AS PROCESSED"


def test___undefined_variable_in_select(holder):
    sql = "SELECT $undefined_var;"
    # Should not raise exception
    h = holder(sql=sql, dialect=DIALECT)
    assert h.query_types == [SelectQuery]
