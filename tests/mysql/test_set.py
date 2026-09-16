import os
import sys

from sqlglot import exp

from sqlleaf.models.query import SetQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__set(holder):
    sql = """
    SET @a = 42;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["a"].to_py() == 42


def test__set_multiple_variables(holder):
    sql = """
    SET @x = 10, @y = 20, @z = 30;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert "x" in h.lineage.object_mapping.session_variables
    assert "y" in h.lineage.object_mapping.session_variables
    assert "z" in h.lineage.object_mapping.session_variables

    assert h.lineage.object_mapping.session_variables["x"].to_py() == 10
    assert h.lineage.object_mapping.session_variables["y"].to_py() == 20
    assert h.lineage.object_mapping.session_variables["z"].to_py() == 30


def test__set_undefined_variable(holder):
    sql = """
    SET @a = @b;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["a"].to_py() == None


# def test__set_system_variable(holder):
#     sql = """
#     SET @@session.sql_mode = 'STRICT_TRANS_TABLES';
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     assert [SetQuery] == h.query_types
#     # TODO: make this a 'system' variable
#     assert h.lineage.object_mapping.session_variables["session.sql_mode"].to_py() == 100


# TODO: this is incorrect. It should be @source = 100, @copy = NULL
def test__set_variable_from_variable(holder):
    sql = """
    SET @source = 100, @copy = @source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["source"].to_py() == 100
    assert h.lineage.object_mapping.session_variables["copy"].to_py() == 100


def test__set_with_subquery(holder):
    sql = """
    SET @count = (SELECT COUNT(*) FROM users);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["count"].sql(dialect=DIALECT) == "(SELECT COUNT(*) FROM users)"


def test__set_mixed_types(holder):
    sql = """
    SET @num = 42, @neg = -42, @str = 'test', @flag = FALSE, @empty = NULL;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["num"].to_py() == 42
    assert h.lineage.object_mapping.session_variables["neg"].to_py() == -42
    assert h.lineage.object_mapping.session_variables["str"].to_py() == "test"
    assert h.lineage.object_mapping.session_variables["flag"].to_py() is False
    assert h.lineage.object_mapping.session_variables["empty"].to_py() is None


def test__set_with_coalesce(holder):
    sql = """
    SET @existing = 'yes';
    SET @value = COALESCE(@existing, 0);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["value"].sql(dialect=DIALECT) == "COALESCE('yes', 0)"


def test__set_with_addition(holder):
    sql = """
    SET @first = 1;
    SET @second = @first + 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.lineage.object_mapping.session_variables["first"].to_py() == 1
    assert h.lineage.object_mapping.session_variables["second"].sql(dialect=DIALECT) == "1 + 1"


def test__set_with_string_operations(holder):
    sql = """
    SET @first = 'Hello', @last = 'World', @full = CONCAT(@first, ' ', @last);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["first"].to_py() == 'Hello'
    assert h.lineage.object_mapping.session_variables["last"].to_py() == 'World'
    assert h.lineage.object_mapping.session_variables["full"].sql(dialect=DIALECT) == "CONCAT('Hello', ' ', 'World')"


def test__set_with_case_expression(holder):
    sql = """
    SET @status = 'active';
    SET @code = CASE @status WHEN 'active' THEN 1 WHEN 'inactive' THEN 0 ELSE -1 END;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery] == h.query_types
    assert "status" in h.lineage.object_mapping.session_variables
    assert "code" in h.lineage.object_mapping.session_variables
    val = h.lineage.object_mapping.session_variables["code"]
    assert "CASE" in val.sql(dialect=DIALECT)
#
#
def test__set_with_date_functions(holder):
    sql = """
    SET @current_time = NOW(), @current_date = CURDATE();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["current_time"].sql(dialect=DIALECT) == "NOW()"
    assert h.lineage.object_mapping.session_variables["current_date"].sql(dialect=DIALECT) == "CURRENT_DATE"


def test__set_variable_reassignment(holder):
    sql = """
    SET @counter = 0;
    SET @counter = @counter + 1;
    SET @counter = @counter + 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery, SetQuery, SetQuery] == h.query_types
    assert "counter" in h.lineage.object_mapping.session_variables


def test__set_with_aggregate_subqueries(holder):
    sql = """
    SET @max_id = (SELECT MAX(id) FROM users), @min_id = (SELECT MIN(id) FROM users);
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.lineage.collected_queries.unsupported) == 1


def test__set_with_equals_operator(holder):
    sql = """
    SET @var1 := 100, @var2 = @var1 := 200;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.session_variables["var1"].to_py() == 100
    assert h.lineage.object_mapping.session_variables["var2"].to_py() == 200


# TODO: system variables can be set like:
# SET SESSION sql_mode = 'TRADITIONAL';
# SET LOCAL sql_mode = 'TRADITIONAL';
# SET @@SESSION.sql_mode = 'TRADITIONAL';
# SET @@LOCAL.sql_mode = 'TRADITIONAL';
# SET @@sql_mode = 'TRADITIONAL';
# SET sql_mode = 'TRADITIONAL';
