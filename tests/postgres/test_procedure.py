import os
import sys

import pytest

from sqlleaf import exception
from sqlleaf.models.query import CallQuery, InsertQuery, ProcedureQuery, ValuesQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__procedure_basic_no_call(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES ('world');
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []


def test__procedure(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES ('world');
    $$;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holders = h.holders[2].downstream_holders
    assert isinstance(downstream_holders[0].original, InsertQuery)
    assert (
        downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )

    assert h.paths == [['literal["world"]', "column[public.target.name]"]]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2:0 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=TEXT properties=[kind=table table=target schema=public]]",
    ]
    assert len(h.edges) == 1


def test__procedure_schema(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE my_schema.hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES ('world');
    $$;
    CALL my_schema.hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holders = h.holders[2].downstream_holders
    assert (
        downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )

    assert h.paths == [['literal["world"]', "column[public.target.name]"]]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2:0 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=TEXT properties=[kind=table table=target schema=public]]",
    ]
    assert len(h.edges) == 1


def test__procedure_with_params(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(greeting TEXT)
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES (greeting);
    $$;
    CALL hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert (
        downstream_holder.transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )


def test__procedure_positional_param(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(TEXT)
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES ($1);
    $$;
    CALL hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert (
        downstream_holder.transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )


def test__procedure_default_value(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(greeting TEXT DEFAULT 'world')
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (name) VALUES (greeting);
    $$;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert (
        downstream_holder.transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )


def test__procedure_multi(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    AS $$
        VALUES (5);
        INSERT INTO public.target (name) VALUES ('world');
    $$;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holders = h.holders[2].downstream_holders
    assert len(downstream_holders) == 2
    assert isinstance(downstream_holders[0].original, ValuesQuery)
    assert isinstance(downstream_holders[1].original, InsertQuery)
    assert (
        downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 'world' AS name"
    )

    assert h.paths == [['literal["world"]', "column[public.target.name]"]]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2:1 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=TEXT properties=[kind=table table=target schema=public]]",
    ]
    assert len(h.edges) == 1


def test__procedure_begin_atomic(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    BEGIN ATOMIC
        INSERT INTO public.target (name) VALUES ('world');
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    # This currently does not work because sqlglot fails to parse BEGIN ATOMIC correctly
    # resulting in no lineage nodes.
    assert len(h.nodes) == 0
    assert h.paths == []

    proc_holder = h.holders[1]
    assert isinstance(proc_holder.original, ProcedureQuery)
    assert (
        proc_holder.transformed.statement.sql(dialect=DIALECT)
        == "CREATE PROCEDURE public.hello() LANGUAGE SQL AS BEGIN atomic; END"
    )


def test__procedure_begin_end(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    BEGIN
        INSERT INTO public.target (name) VALUES ('world');
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['literal["world"]', "column[public.target.name]"]]


def test__procedure_positional_notation(holder):
    sql = """
    CREATE TABLE target (a INT, b INT);
    CREATE PROCEDURE my_proc(x INT, y INT)
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (a, b) VALUES (x, y);
    $$;
    CALL my_proc(10, 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert (
        downstream_holder.transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (a, b) SELECT 10 AS a, 20 AS b"
    )
    assert h.paths == [
        ["literal[10]", "column[public.target.a]"],
        ["literal[20]", "column[public.target.b]"],
    ]


def test__procedure_mixed_notation(holder):
    sql = """
    CREATE TABLE target (a INT, b INT);
    CREATE PROCEDURE my_proc(x INT, y INT)
    LANGUAGE SQL
    AS $$
        INSERT INTO public.target (a, b) VALUES (x, y);
    $$;
    CALL my_proc(10, y => 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    downstream_holder = h.holders[2].downstream_holders[0]
    assert isinstance(downstream_holder.original, InsertQuery)
    assert (
        downstream_holder.transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (a, b) SELECT 10 AS a, 20 AS b"
    )


def test__procedure_in_out_params(holder):
    sql = """
    CREATE PROCEDURE my_proc(IN x INT, OUT y INT)
    LANGUAGE SQL
    AS $$
        SELECT x;
    $$;
    CALL my_proc(10, NULL);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 2

    proc_query = h.holders[0].original
    assert isinstance(proc_query, ProcedureQuery)
    assert len(proc_query.parameters) == 2
    assert proc_query.parameters[0].name == "x"
    assert proc_query.parameters[0].is_input is True
    assert proc_query.parameters[1].name == "y"
    assert proc_query.parameters[1].is_output is True

    call_query = h.holders[1].original
    assert isinstance(call_query, CallQuery)
    assert len(call_query.args) == 2

    downstream_holder = h.holders[1].downstream_holders[0]
    assert downstream_holder.transformed.statement.sql(dialect=DIALECT) == 'SELECT 10 AS "10"'


# TODO: test chained procs
# TODO: nested statements


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
    assert h.paths == [["literal[1]", "column[public.target.a]"]]


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
