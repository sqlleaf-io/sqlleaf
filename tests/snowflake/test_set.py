import os
import sys

from sqlglot import exp

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import SetQuery

DIALECT = "snowflake"


def test___set_simple(holder):
    sql = """
    SET a = 10;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "A" in h.lineage.object_mapping.session_variables
    val = h.lineage.object_mapping.session_variables["A"]
    assert isinstance(val, exp.Literal)
    assert val.sql(dialect=DIALECT) == "10"


def test___set_multiple_variables(holder):
    sql = """
    SET (a, b) = (10, 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "A" in h.lineage.object_mapping.session_variables
    assert "B" in h.lineage.object_mapping.session_variables
    assert h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT) == "10"
    assert h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT) == "20"


def test___set_multiple_statements(holder):
    sql = """
    SET a = 10;
    SET b = 20;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery] == h.query_types
    assert "A" in h.lineage.object_mapping.session_variables
    assert "B" in h.lineage.object_mapping.session_variables
    assert h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT) == "10"
    assert h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT) == "20"


def test___set_subquery(holder):
    sql = """
    SET a = (SELECT max(col) FROM my_table);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "A" in h.lineage.object_mapping.session_variables
    assert "SELECT MAX(COL) FROM MY_TABLE" in h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT)


def test___set_multiple_subquery(holder):
    sql = """
    SET (a, b) = (SELECT col1, col2 FROM table LIMIT 1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "A" in h.lineage.object_mapping.session_variables
    assert "B" in h.lineage.object_mapping.session_variables

    assert "(SELECT COL1 FROM TABLE LIMIT 1)" in h.lineage.object_mapping.session_variables["A"].sql(dialect=DIALECT)
    assert "(SELECT COL2 FROM TABLE LIMIT 1)" in h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT)


def test___set_variable_composition(holder):
    sql = """
    SET a = 1;
    SET b = $a + 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery] == h.query_types
    assert "$a + 1" == h.lineage.object_mapping.session_variables["B"].sql(dialect=DIALECT)
