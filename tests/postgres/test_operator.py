import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__operator_binary(holder):
    sql = """
    CREATE TABLE target(name INT);

    INSERT INTO target (name) SELECT 3 OPERATOR(pg_catalog.+) 4;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 7 AS name"
    )


def test__operator_binary_unqualified(holder):
    sql = """
    CREATE TABLE target(name INT);

    INSERT INTO target (name) SELECT 3 OPERATOR(pg_catalog.+) 4;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT 7 AS name"
    )


def test__operator_prefix_negate_fails(holder):
    sql = """
    CREATE TABLE source(a INT);
    CREATE TABLE target(name INT);

    INSERT INTO target (name) SELECT OPERATOR(pg_catalog.-) a AS name FROM public.source;
    """
    with pytest.raises(sqlglot.errors.ParseError):
        holder(sql=sql, dialect=DIALECT)


def test__operator_prefix_bitwise_not_fails(holder):
    sql = """
    CREATE TABLE source(a INT);
    CREATE TABLE target(name INT);

    INSERT INTO target (name) SELECT OPERATOR(pg_catalog.~) a AS name FROM public.source;
    """
    with pytest.raises(sqlglot.errors.ParseError):
        holder(sql=sql, dialect=DIALECT)


def test__operator_multiple_occurrences(holder):
    sql = """
    CREATE TABLE source(a INT, b INT, s VARCHAR);
    CREATE TABLE target(name INT, other VARCHAR, modulo INT);

    INSERT INTO target (name, other, modulo)
    SELECT a OPERATOR(pg_catalog.+) b OPERATOR(pg_catalog.*) 2 AS name,
           s OPERATOR(pg_catalog.||) 'def' AS other,
           a OPERATOR(pg_catalog.%) 3 AS modulo
    FROM public.source;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name, other, modulo) SELECT (source.a + source.b) * 2 AS name, source.s || 'def' AS other, source.a % 3 AS modulo FROM public.source AS source"
    )
