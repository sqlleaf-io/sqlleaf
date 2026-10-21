import os
import sys

import pytest

from sqlleaf import exception
from sqlleaf.models.query import CallQuery, InsertQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = ""


def test_procedure_does_not_exist(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE TABLE target (name TEXT);
        CREATE PROCEDURE hello()
        LANGUAGE SQL
        BEGIN
            SELECT 1;
            INSERT INTO target (name) VALUES ('world');
        END;

        CALL hello('Hello');
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_too_few_args_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(a INT, b INT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;

        CALL p(1);
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_omitted_default_succeeds(holder):
    sql = """
    CREATE PROCEDURE p(a TEXT DEFAULT 'x')
    LANGUAGE SQL
    BEGIN
        SELECT a;
    END;

    CALL p();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert isinstance(h.holders[-1].original, CallQuery)


def test_call_named_args_succeeds(holder):
    sql = """
    CREATE TABLE target (a INT, b TEXT);
    CREATE PROCEDURE p(a INT, b TEXT)
    LANGUAGE SQL
    BEGIN
        INSERT INTO target (a, b) VALUES (a, b);
    END;

    CALL p(b => 'x', a => 1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3
    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)


def test_call_unknown_named_arg_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(a INT, b TEXT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;

        CALL p(c => 1);
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_duplicate_named_and_positional_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(a INT, b TEXT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;

        CALL p(1, a => 2);
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_out_param_counted_succeeds(holder):
    sql = """
    CREATE PROCEDURE p(IN x INT, OUT y INT)
    LANGUAGE SQL
    BEGIN
        SELECT x;
    END;

    CALL p(1, NULL);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 2
    assert isinstance(h.holders[1].original, CallQuery)


def test_call_missing_out_param_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(IN x INT, OUT y INT)
        LANGUAGE SQL
        BEGIN
            SELECT x;
        END;

        CALL p(1);
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_unknown_procedure_does_not_raise(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CALL missing(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.nodes) == 0


def test_call_arg_type_mismatch_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(a INT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;

        CALL p('abc');
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_matching_arg_types_succeeds(holder):
    sql = """
    CREATE TABLE target (a INT, b TEXT);
    CREATE PROCEDURE p(a INT, b TEXT)
    LANGUAGE SQL
    BEGIN
        INSERT INTO target (a, b) VALUES (a, b);
    END;

    CALL p(1, 'x');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3
    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)


def test_call_overload_matches_one_signature(holder):
    sql = """
    CREATE TABLE target (a INT);
    CREATE PROCEDURE p(a INT)
    LANGUAGE SQL
    BEGIN
        INSERT INTO target (a) VALUES (a);
    END;
    CREATE PROCEDURE p(a INT, b INT)
    LANGUAGE SQL
    BEGIN
        SELECT a;
    END;

    CALL p(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[-1].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert h.paths == [["literal[1]", "column[target.a]"]]


def test_call_overload_matches_no_signature_raises(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE PROCEDURE p(a INT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;
        CREATE PROCEDURE p(a INT, b INT)
        LANGUAGE SQL
        BEGIN
            SELECT a;
        END;

        CALL p(1, 2, 3);
        """
        holder(sql=sql, dialect=DIALECT)
    assert "No matching procedure signatures found" in str(exc_info.value)


def test_call_null_arg_to_int_input_succeeds(holder):
    sql = """
    CREATE PROCEDURE p(a INT)
    LANGUAGE SQL
    BEGIN
        SELECT a;
    END;

    CALL p(NULL);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 2
    assert isinstance(h.holders[1].original, CallQuery)
