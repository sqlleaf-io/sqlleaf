import os
import sys
import typing as t

import pytest
import sqlglot
from sqlglot import exp

from sqlleaf.models.query import ProcedureQuery, CallQuery, InsertQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def to_sql(expressions: t.List[exp.Expr]) -> t.List[str]:
    return [e.sql(dialect="postgres") for e in expressions]


def test_hello_procedure(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES ('world');
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.edges) == 0

    assert query.procedure == "hello"
    assert not query.schema
    assert query.args == []


def test_call_procedure(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES ('world');
    $$;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)

    assert call_query.procedure == "hello"
    assert call_query.args == []

    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'world' AS name"

    assert h.paths == [['literal["world"]', 'column[target.name]']]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
        'column[name=name type=TEXT properties=[kind=table table=target]]'
    ]
    assert len(h.edges) == 1


def test_call_schema_procedure(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE my_schema.hello()
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES ('world');
    $$;
    CALL my_schema.hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)
    assert proc_query.procedure == "hello"
    assert proc_query.schema == "my_schema"

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)

    assert call_query.procedure == "hello"
    assert call_query.schema == "my_schema"
    assert call_query.name == "my_schema.hello"
    assert call_query.args == []

    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'world' AS name"

    assert h.paths == [['literal["world"]', 'column[target.name]']]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
        'column[name=name type=TEXT properties=[kind=table table=target]]'
    ]
    assert len(h.edges) == 1


def test_call_procedure_with_params(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(greeting TEXT)
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES (greeting);
    $$;
    CALL hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)
    assert proc_query.procedure == "hello"
    assert len(proc_query.parameters) == 1
    assert proc_query.parameters[0].name == "greeting"

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)
    assert call_query.procedure == "hello"
    assert len(call_query.args) == 1

    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'world' AS name"


def test_call_procedure_positional_param(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(TEXT)
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES ($1);
    $$;
    CALL hello('world');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)
    assert proc_query.procedure == "hello"
    assert len(proc_query.parameters) == 1
    assert proc_query.parameters[0].name == "$1"

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)
    assert call_query.procedure == "hello"
    assert len(call_query.args) == 1

    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'world' AS name"


def test_call_procedure_default_value(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello(greeting TEXT DEFAULT 'world')
    LANGUAGE SQL
    AS $$
        INSERT INTO target (name) VALUES (greeting);
    $$;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)
    assert proc_query.procedure == "hello"
    assert len(proc_query.parameters) == 1
    assert proc_query.parameters[0].name == "greeting"
    assert proc_query.parameters[0].default.sql(dialect=DIALECT) == "'world'"

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)
    assert call_query.procedure == "hello"
    assert call_query.args == []

    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'world' AS name"


def test_procedure_begin_atomic(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    BEGIN ATOMIC
        INSERT INTO target (name) VALUES ('world');
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)
    # This currently does not work because sqlglot fails to parse BEGIN ATOMIC correctly
    # resulting in no lineage nodes.
    assert len(h.nodes) == 0


def test_procedure_begin_end(holder):
    sql = """
    CREATE TABLE target (name TEXT);
    CREATE PROCEDURE hello()
    LANGUAGE SQL
    BEGIN
        INSERT INTO target (name) VALUES ('world');
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    # Should have 3 queries: Table, Procedure, Call
    assert len(h.holders) == 3

    proc_query = h.holders[1].original
    assert isinstance(proc_query, ProcedureQuery)
    assert proc_query.procedure == "hello"
    # EndStatement should be filtered out
    assert all(not isinstance(stmt, exp.EndStatement) for stmt in proc_query.inner_statements)

    call_query = h.holders[2].original
    assert isinstance(call_query, CallQuery)
    assert call_query.procedure == "hello"


# OUT params
# NULL for out params


def test_call_procedure_positional_notation(holder):
    sql = """
    CREATE TABLE target (a INT, b INT);
    CREATE PROCEDURE my_proc(x INT, y INT)
    LANGUAGE SQL
    AS $$
        INSERT INTO target (a, b) VALUES (x, y);
    $$;
    CALL my_proc(10, 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3
    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (a, b) SELECT 10 AS a, 20 AS b"


def test_call_procedure_mixed_notation(holder):
    sql = """
    CREATE TABLE target (a INT, b INT);
    CREATE PROCEDURE my_proc(x INT, y INT)
    LANGUAGE SQL
    AS $$
        INSERT INTO target (a, b) VALUES (x, y);
    $$;
    CALL my_proc(10, y => 20);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 3
    substituted = h.holders[2].substituted
    assert isinstance(substituted, InsertQuery)
    assert substituted.statement.sql(dialect=DIALECT) == "INSERT INTO target (a, b) SELECT 10 AS a, 20 AS b"


def test_call_procedure_in_out_params(holder):
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

    substituted = h.holders[1].substituted
    assert substituted.statement.sql(dialect=DIALECT) == 'SELECT 10 AS "10"'


# TODO: test chained procs
# TODO: nested statements
