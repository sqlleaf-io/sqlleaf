import os
import sys

import pytest
import sqlglot

from sqlleaf.models.query import ProcedureQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


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
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is True
    assert query.parameters[0].is_output is False

    assert h.paths == [['literal["Earth"]', "column[target.name]"]]
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
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is False
    assert query.parameters[0].is_output is True

    assert len(h.edges) == 1


def test__procedure_declare_variable(holder):
    sql = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE PROCEDURE hello()
    BEGIN
        DECLARE greeting VARCHAR(255) DEFAULT 'world';
        INSERT INTO target (name) VALUES (greeting);
    END;
    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [d.transformed.statement.sql(dialect=DIALECT) for d in h.holders[2].downstream_holders] == [
        "DECLARE greeting VARCHAR(255) = 'world'",
        "INSERT INTO target (name) SELECT 'world' AS name",
    ]

    assert h.paths == [['literal["world"]', "column[target.name]"]]
    assert len(h.edges) == 1


DECLARE_PROCEDURE_TEMPLATE = """
    CREATE TABLE target (name VARCHAR(255));
    CREATE TABLE table1 (id INT, xname VARCHAR(5));
    CREATE PROCEDURE hello()
    BEGIN
        {declare}
        INSERT INTO target (name) VALUES ({value});
    END;
    CALL hello();
    """


def _declare_holder(holder, declare: str, value: str = "'world'"):
    return holder(sql=DECLARE_PROCEDURE_TEMPLATE.format(declare=declare, value=value), dialect=DIALECT)


def _downstream_sql(h) -> list[str]:
    return [d.transformed.statement.sql(dialect=DIALECT) for d in h.holders[3].downstream_holders]


def test__procedure_declare_default_varchar(holder):
    h = _declare_holder(holder, "DECLARE xname VARCHAR(5) DEFAULT 'bob';", "xname")

    assert _downstream_sql(h) == [
        "DECLARE xname VARCHAR(5) = 'bob'",
        "INSERT INTO target (name) SELECT 'bob' AS name",
    ]
    assert h.paths == [['literal["bob"]', "column[target.name]"]]


def test__procedure_declare_no_default(holder):
    h = _declare_holder(holder, "DECLARE newname VARCHAR(5);", "newname")

    assert _downstream_sql(h) == [
        "DECLARE newname VARCHAR(5)",
        "INSERT INTO target (name) SELECT NULL AS name",
    ]


def test__procedure_declare_int(holder):
    h = _declare_holder(holder, "DECLARE xid INT;", "xid")

    assert _downstream_sql(h) == [
        "DECLARE xid INT",
        "INSERT INTO target (name) SELECT NULL AS name",
    ]


def test__procedure_declare_tinyint_default(holder):
    h = _declare_holder(holder, "DECLARE done TINYINT DEFAULT 0;", "done")

    assert _downstream_sql(h) == [
        "DECLARE done TINYINT = 0",
        "INSERT INTO target (name) SELECT 0 AS name",
    ]
    assert h.paths == [["literal[0]", "column[target.name]"]]


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
    assert query.parameters[0].name == "address"
    assert query.parameters[0].is_input is True
    assert query.parameters[0].is_output is True

    assert h.paths == [['literal["Earth"]', "column[target.name]"]]
    assert len(h.edges) == 1


# TODO: MySQL cursors when they're supported


# Different from the regular CASE _operator_; this allows queries inside it and has semicolons
def test__procedure_case_fails():
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        CREATE PROCEDURE p()
          BEGIN
            DECLARE v INT DEFAULT 1;
            CASE v
              WHEN 2 THEN SELECT 1;
              ELSE
                BEGIN
                END;
            END CASE;
          END;
        """
        sqlglot.parse(sql, dialect=DIALECT)

    assert e.value.args[0].startswith("Required keyword: 'true' missing for")
