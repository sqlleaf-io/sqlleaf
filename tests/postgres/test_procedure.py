import os
import sys

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

    assert h.paths == [['literal["world"]', "column[public.target.name]"]]


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
