import os
import sys

import pytest
import sqlglot

from sqlleaf import exception
from sqlleaf.models.query import PrepareQuery
from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "mysql"


def test__prepare_select_constant(holder):
    sql = """
    PREPARE stmt1 FROM 'SELECT 1';
    EXECUTE stmt1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    substituted = h.holders[-1].transformed.holder.downstream_holders[0].original
    assert substituted.statement.sql(dialect=DIALECT) == "SELECT 1 AS `1`"
    assert h.paths == []
    assert h.nodes_full == []


def test__prepare_select_sqrt_single_quotes(holder):
    sql = """
    PREPARE stmt1 FROM 'SELECT SQRT(POW(?,2) + POW(?,2)) AS hypotenuse';
    SET @a = 3, @b = 4;
    EXECUTE stmt1 USING @a, @b;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    prepare_query: PrepareQuery = h.lineage.object_mapping.lookup_prepare_query(sqlglot.exp.to_table("stmt1"))
    assert prepare_query.source_info.type == SqlObjectType.SELECT
    assert prepare_query.target_info.type == SqlObjectType.PREPARED_STATEMENT

    substituted = h.holders[-1].transformed.holder.downstream_holders[0].original
    assert substituted.statement.sql(dialect=DIALECT) == "SELECT SQRT(POWER(3, 2) + POWER(4, 2)) AS hypotenuse"
    assert h.paths == []
    assert h.nodes_full == []


def test__prepare_select_sqrt_double_quotes(holder):
    sql = """
    PREPARE stmt1 FROM "SELECT SQRT(POW(?,2) + POW(?,2)) AS hypotenuse";
    SET @a = 3, @b = 4;
    EXECUTE stmt1 USING @a, @b;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    substituted = h.holders[-1].transformed.holder.downstream_holders[0].original
    assert substituted.statement.sql(dialect=DIALECT) == "SELECT SQRT(POWER(3, 2) + POWER(4, 2)) AS hypotenuse"
    assert h.paths == []
    assert h.nodes_full == []


def test__prepare_select_with_placeholder(holder):
    sql = """
    CREATE TABLE source(name VARCHAR(50), amount INT);

    PREPARE stmt1 FROM 'SELECT name, amount FROM source WHERE amount > ?';
    SET @min = 10;
    EXECUTE stmt1 USING @min;
    """
    h = holder(sql=sql, dialect=DIALECT)

    substituted = h.holders[-1].transformed.holder.downstream_holders[0].original
    assert substituted.statement.sql(dialect=DIALECT) == (
        "SELECT source.name AS name, source.amount AS amount FROM source AS source WHERE source.amount > 10"
    )
    assert h.paths == []
    assert h.nodes_full == []


def test__prepare_insert(holder):
    sql = """
    CREATE TABLE source(name VARCHAR(50), amount INT);
    CREATE TABLE target(name VARCHAR(50), amount INT);

    PREPARE stmt1 FROM 'INSERT INTO target SELECT name, amount FROM source';
    EXECUTE stmt1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    prepare_query: PrepareQuery = h.lineage.object_mapping.lookup_prepare_query(sqlglot.exp.to_table("stmt1"))
    assert prepare_query.source_info.type == SqlObjectType.DML

    insert_query = h.holders[-1].transformed.holder.downstream_holders[0].transformed
    assert insert_query.source_info.type == SqlObjectType.SELECT
    assert insert_query.target_info.type == SqlObjectType.TABLE
    assert h.paths == [
        ["column[source.name]", "column[target.name]"],
        ["column[source.amount]", "column[target.amount]"],
    ]
    assert len(h.edges) == 2


def test__prepare_existing_name_is_replaced_implicitly(holder):
    sql = """
    CREATE TABLE source(name VARCHAR(50), amount INT);

    PREPARE stmt1 FROM 'SELECT name FROM source WHERE amount > ?';
    PREPARE stmt1 FROM 'SELECT name, amount FROM source';
    EXECUTE stmt1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    prepare_query: PrepareQuery = h.lineage.object_mapping.lookup_prepare_query(sqlglot.exp.to_table("stmt1"))
    assert prepare_query.source_info.type == SqlObjectType.SELECT
    assert len(list(prepare_query.source_info.expression.find_all(sqlglot.exp.Placeholder))) == 0

    substituted = h.holders[-1].transformed.holder.downstream_holders[0].original
    assert substituted.statement.sql(dialect=DIALECT) == (
        "SELECT source.name AS name, source.amount AS amount FROM source AS source"
    )
    assert h.paths == []
    assert h.nodes_full == []


def test__prepare_in_procedure_rejects_parameter(holder):
    sql = """
    CREATE TABLE target(name VARCHAR(50));

    CREATE PROCEDURE make_stmt(IN n VARCHAR(50))
    BEGIN
        PREPARE stmt1 FROM 'INSERT INTO target (name) VALUES (n)';
    END;

    CALL make_stmt('Earth');
    """
    with pytest.raises(
        exception.InvalidQueryError, match="Prepared statement 'stmt1' cannot refer to the stored program variable 'n'"
    ):
        holder(sql=sql, dialect=DIALECT)


def test__prepare_in_procedure_rejects_local_variable(holder):
    sql = """
    CREATE TABLE target(name VARCHAR(50));

    CREATE PROCEDURE make_stmt()
    BEGIN
        DECLARE greeting VARCHAR(50) DEFAULT 'Earth';
        PREPARE stmt1 FROM 'INSERT INTO target (name) VALUES (greeting)';
    END;

    CALL make_stmt();
    """
    with pytest.raises(
        exception.InvalidQueryError,
        match="Prepared statement 'stmt1' cannot refer to the stored program variable 'greeting'.",
    ):
        holder(sql=sql, dialect=DIALECT)


def test__prepare_in_procedure_accepts_user_variable(holder):
    sql = """
    CREATE TABLE target(name VARCHAR(50));

    CREATE PROCEDURE make_stmt()
    BEGIN
        PREPARE stmt1 FROM 'INSERT INTO target (name) VALUES (@greeting)';
    END;

    SET @greeting = 'Earth';
    CALL make_stmt();
    EXECUTE stmt1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    prepare_query: PrepareQuery = h.lineage.object_mapping.lookup_prepare_query(sqlglot.exp.to_table("stmt1"))
    assert prepare_query.source_info.type == SqlObjectType.DML


def test__prepare_in_procedure_persists_after_call(holder):
    sql = """
    CREATE TABLE source(name VARCHAR(50), amount INT);
    CREATE TABLE target(name VARCHAR(50), amount INT);

    CREATE PROCEDURE make_stmt()
    BEGIN
        PREPARE stmt1 FROM 'INSERT INTO target SELECT name, amount FROM source';
    END;

    CALL make_stmt();
    EXECUTE stmt1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0
    prepare_query: PrepareQuery = h.lineage.object_mapping.lookup_prepare_query(sqlglot.exp.to_table("stmt1"))
    assert prepare_query.source_info.type == SqlObjectType.DML

    insert_query = h.holders[-1].transformed.holder.downstream_holders[0].transformed
    assert insert_query.source_info.type == SqlObjectType.SELECT
    assert insert_query.target_info.type == SqlObjectType.TABLE
    assert h.paths == [
        ["column[source.name]", "column[target.name]"],
        ["column[source.amount]", "column[target.amount]"],
    ]
    assert len(h.edges) == 2
