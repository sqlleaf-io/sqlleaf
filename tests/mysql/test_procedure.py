import os
import sys

from sqlglot import exp

from sqlleaf.models.query import ProcedureQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def to_sql(expressions: list[exp.Expr]) -> list[str]:
    return [e.sql(dialect=DIALECT) for e in expressions]


# TODO: get tests from https://dev.mysql.com/doc/refman/8.4/en/call.html


def test__procedure_simple(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello()
    BEGIN
        INSERT INTO target (name) VALUES ('world');
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)

    assert h.paths == [
        ['literal["world"]', "column[target.name]"],
    ]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=2:0 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=VARCHAR(255) properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 1


def test__procedure_params(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello(address VARCHAR)
    BEGIN
        INSERT INTO target (name) VALUES ('world');
    END;
    SET @addr = 'Earth';
    CALL hello(@addr);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)

    assert h.paths == [
        ['literal["world"]', "column[target.name]"],
    ]
    assert h.nodes_full == [
        'literal[name="world" type=VARCHAR position=[query_depth=0 query_width=0 statement=3:0 select=0 func_depth=0 func_arg=0]]',
        "column[name=name type=VARCHAR(255) properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 1


def test__procedure_in_param(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello(IN address VARCHAR(255))
    BEGIN
        INSERT INTO target (name) VALUES (address);
    END;
    CALL hello('Earth');
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is True
    assert query.parameters[0].is_output is False

    assert h.paths == [
        ['literal["Earth"]', "column[target.name]"],
    ]
    assert len(h.edges) == 1


def test__procedure_out_param(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello(OUT address VARCHAR(255))
    BEGIN
        SET address = 'world';
        INSERT INTO target (name) VALUES (address);
    END;
    CALL hello(@addr);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is False
    assert query.parameters[0].is_output is True

    assert len(h.edges) == 1


def test__procedure_inout_param(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello(INOUT address VARCHAR(255))
    BEGIN
        INSERT INTO target (name) VALUES (address);
        SET @address = 'Mars';
    END;
    SET address = 'Earth';
    CALL hello(@address);
    SELECT @address;
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, ProcedureQuery)
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is True
    assert query.parameters[0].is_output is True

    assert h.paths == [
        ['literal["Earth"]', "column[target.name]"],
    ]
    assert len(h.edges) == 1
