import os
import sys

import pytest
import sqlglot

from sqlleaf.processors.transformer.expressions.format import (
    pg_format,
    quote_ident,
    quote_literal,
    quote_nullable,
    simplify_format,
)
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def _args(sql: str):
    return {"sql": sqlglot.parse_one(sql, dialect="postgres"), "dialect": "postgres"}


def test__format(holder):
    sql = """
    SELECT FORMAT('%s', 'hello')
    """
    out = simplify_format(**_args(sql)).sql(dialect=DIALECT)
    assert out == "SELECT 'hello'"


def test__example_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        COPY (INSERT INTO fruit.simple (name) VALUES ('cherry') RETURNING name) TO STDOUT
        """
        h = holder(**_args(sql), dialect=DIALECT)
        assert h.paths == [
            ['literal["cherry"]', "column[fruit.simple.name]", "stream[stdout]"],
        ]
    assert "Expecting )." in e.value.args[0]


def test__format_positional():
    sql = "SELECT FORMAT('%1$s %2$s %1$s', 'foo', 'bar')"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT 'foo bar foo'"


def test__format_literals_and_identifiers():
    sql = "SELECT FORMAT('%I, %L, %L', 'user', 'hello', NULL)"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT '\"user\", ''hello'', NULL'"


def test__format_width_and_flags():
    sql = "SELECT FORMAT('|%10s| |%-10s| |%*s| |%5$-*6$s|', 'abc', 'def', 5, 'gh', 'ij', 6)"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT '|       abc| |def       | |   gh| |ij    |'"


def test__format_nested():
    sql = "SELECT FORMAT('%s -> %s', 'outer', FORMAT('%s', 'inner'))"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT 'outer -> inner'"

    sql_multi_nested = "SELECT FORMAT('%s and %s', FORMAT('1 %s', 'a'), FORMAT('2 %s', 'b'))"
    assert simplify_format(**_args(sql_multi_nested)).sql(dialect=DIALECT) == "SELECT '1 a and 2 b'"


def test__format_percent_escape():
    sql = "SELECT FORMAT('100%% %s', 'complete')"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT '100% complete'"


def test__format_errors():
    with pytest.raises(ValueError, match="unterminated"):
        simplify_format(**_args("SELECT FORMAT('hello %')"))

    with pytest.raises(ValueError, match="unrecognized"):
        simplify_format(**_args("SELECT FORMAT('%z', 'val')"))

    with pytest.raises(ValueError, match="too few arguments"):
        simplify_format(**_args("SELECT FORMAT('%s %s', 'val')"))

    with pytest.raises(ValueError, match="argument 0"):
        simplify_format(**_args("SELECT FORMAT('%0$s', 'val')"))

    with pytest.raises(ValueError, match="null values cannot be formatted as an SQL identifier"):
        simplify_format(**_args("SELECT FORMAT('%I', NULL)"))

    with pytest.raises(ValueError, match="format\\(\\) template must be a string"):
        simplify_format(**_args("SELECT FORMAT(123, 'val')"))


def test__simplify_format_complex_query():
    sql = "SELECT FORMAT('SELECT %I FROM %I WHERE %I = %L', 'col', 'tbl', 'status', 'active')"
    assert (
        simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT 'SELECT col FROM tbl WHERE status = ''active'''"
    )

    cte_sql = "WITH t AS (SELECT FORMAT('%s', 'a') AS col) SELECT * FROM t"
    assert simplify_format(**_args(cte_sql)).sql(dialect=DIALECT) == "WITH t AS (SELECT 'a' AS col) SELECT * FROM t"


def test__pg_format_direct():
    assert pg_format("hello %s", "world") == "hello world"
    assert pg_format("%1$s %2$s %1$s", "a", "b") == "a b a"
    assert pg_format("%I %L %s", "col", "val", None) == "col 'val' "
    assert pg_format("%s %L %I", True, True, "col") == "t 't' col"
    assert pg_format("%s %L", None, None) == " NULL"
    assert pg_format("|%10s|", "abc") == "|       abc|"
    assert pg_format("|%-10s|", "abc") == "|abc       |"
    assert pg_format("|%*s|", 10, "abc") == "|       abc|"
    assert pg_format("|%*s|", -10, "hello") == "|hello     |"
    assert pg_format("|%*I|", 10, "col") == "|       col|"
    assert pg_format("|%1$-*2$s|", "abc", 10) == "|abc       |"
    assert pg_format("100%% %s", "done") == "100% done"

    with pytest.raises(ValueError, match="unrecognized"):
        pg_format("%1$%", "a")

    with pytest.raises(ValueError, match="unrecognized"):
        pg_format("%-5%", "a")


def test__quoting_functions():
    # quote_ident
    assert quote_ident("foo") == "foo"
    assert quote_ident("Foo") == '"Foo"'
    assert quote_ident("foo bar") == '"foo bar"'
    assert quote_ident('foo"bar') == '"foo""bar"'
    assert quote_ident("select") == '"select"'
    assert quote_ident("all") == '"all"'
    assert quote_ident("user") == '"user"'
    assert quote_ident("_valid_123") == "_valid_123"
    assert quote_ident("123abc") == '"123abc"'
    assert quote_ident(None) is None

    # quote_literal
    assert quote_literal("hello") == "'hello'"
    assert quote_literal("it's") == "'it''s'"
    assert quote_literal(None) is None
    assert quote_literal(True) == "'t'"
    assert quote_literal(False) == "'f'"
    assert quote_literal(123) == "'123'"

    # quote_nullable
    assert quote_nullable("hello") == "'hello'"
    assert quote_nullable(None) == "NULL"


def test__simplify_format_expressions():
    sql = "SELECT FORMAT('%s, %s, %s, %s', quote_ident('col'), quote_literal('val'), quote_nullable(NULL), -5)"
    assert simplify_format(**_args(sql)).sql(dialect=DIALECT) == "SELECT 'col, ''val'', NULL, -5'"

    sql_cast_paren = "SELECT FORMAT('%s, %s', CAST('hello' AS TEXT), ('world'))"
    assert simplify_format(**_args(sql_cast_paren)).sql(dialect=DIALECT) == "SELECT 'hello, world'"

    with pytest.raises(ValueError, match="cannot evaluate format\\(\\) argument"):
        simplify_format(**_args("SELECT FORMAT('%s', col_name)"))


def test__pg_format_additional_edge_cases():
    assert pg_format("plain text without percent") == "plain text without percent"
    assert pg_format("%*2$s", "abc", 5) == "  abc"

    with pytest.raises(ValueError, match="null width is not allowed"):
        pg_format("%*s", None, "abc")

    with pytest.raises(ValueError, match="null width is not allowed"):
        pg_format("%*1$s", None)

    with pytest.raises(ValueError, match="argument 0"):
        pg_format("%*0$s", 5, "abc")

    with pytest.raises(ValueError, match="too few arguments"):
        pg_format("%*5$s", "abc")
