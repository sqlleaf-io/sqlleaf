from sqlleaf.dialects.loader import get_object_ddl
from tests.new_fixtures import holder as holder

DIALECT = "postgres"
SQL = get_object_ddl("pg_catalog", "pg_policies", DIALECT)


def test__system_view_target_has_no_lineage(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.nodes == []
    assert h.edges == []
    assert h.paths == []


def test__insert_select_from_system_view_has_lineage(holder):
    sql = SQL + (
        """
    CREATE TABLE public.archive (schemaname VARCHAR, tablename VARCHAR);
    INSERT INTO public.archive (schemaname, tablename) SELECT schemaname, tablename FROM pg_catalog.pg_policies;
    """
    )
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[pg_catalog.pg_policies.schemaname]", "column[public.archive.schemaname]"],
        ["column[pg_catalog.pg_policies.tablename]", "column[public.archive.tablename]"],
    ]


def test__system_function_aclexplode(holder):
    sql = """
    CREATE TABLE public.target (grantor VARCHAR, grantee VARCHAR, privilege_type VARCHAR, is_grantable VARCHAR);

    INSERT INTO public.target
    SELECT * FROM aclexplode('{postgres=arwdDxt/postgres}'::aclitem[]);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (grantor, grantee, privilege_type, is_grantable) SELECT aclexplode.grantor AS grantor, aclexplode.grantee AS grantee, aclexplode.privilege_type AS privilege_type, aclexplode.is_grantable AS is_grantable FROM ACLEXPLODE(CAST('{postgres=arwdDxt/postgres}' AS aclitem[])) AS aclexplode(grantor, grantee, privilege_type, is_grantable)"""
    )


def test__system_function_json_array_elements(holder):
    sql = """
    CREATE TABLE public.target (value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_array_elements('[1,2]'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (value) SELECT json_array_elements.value AS value FROM JSON_ARRAY_ELEMENTS(CAST('[1,2]' AS JSON)) AS json_array_elements(value)"""
    )


def test__system_function_json_array_elements_text(holder):
    sql = """
    CREATE TABLE public.target (value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_array_elements_text('["a","b"]'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (value) SELECT json_array_elements_text.value AS value FROM JSON_ARRAY_ELEMENTS_TEXT(CAST('["a","b"]' AS JSON)) AS json_array_elements_text(value)"""
    )


def test__system_function_json_each(holder):
    sql = """
    CREATE TABLE public.target (key VARCHAR, value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_each('{"a":"x"}'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (key, value) SELECT json_each.key AS key, json_each.value AS value FROM JSON_EACH(CAST('{"a":"x"}' AS JSON)) AS json_each(key, value)"""
    )


def test__system_function_json_each_text(holder):
    sql = """
    CREATE TABLE public.target (key VARCHAR, value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_each_text('{"a":"x"}'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (key, value) SELECT json_each_text.key AS key, json_each_text.value AS value FROM JSON_EACH_TEXT(CAST('{"a":"x"}' AS JSON)) AS json_each_text(key, value)"""
    )


def test__system_function_jsonb_array_elements(holder):
    sql = """
    CREATE TABLE public.target (value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM jsonb_array_elements('[1,2]'::jsonb);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (value) SELECT jsonb_array_elements.value AS value FROM JSONB_ARRAY_ELEMENTS(CAST('[1,2]' AS JSONB)) AS jsonb_array_elements(value)"""
    )


def test__system_function_jsonb_array_elements_text(holder):
    sql = """
    CREATE TABLE public.target (value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM jsonb_array_elements_text('["a","b"]'::jsonb);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (value) SELECT jsonb_array_elements_text.value AS value FROM JSONB_ARRAY_ELEMENTS_TEXT(CAST('["a","b"]' AS JSONB)) AS jsonb_array_elements_text(value)"""
    )


def test__system_function_jsonb_each(holder):
    sql = """
    CREATE TABLE public.target (key VARCHAR, value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM jsonb_each('{"a":"x"}'::jsonb);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (key, value) SELECT jsonb_each.key AS key, jsonb_each.value AS value FROM JSONB_EACH(CAST('{"a":"x"}' AS JSONB)) AS jsonb_each(key, value)"""
    )


def test__system_function_jsonb_each_text(holder):
    sql = """
    CREATE TABLE public.target (key VARCHAR, value VARCHAR);

    INSERT INTO public.target
    SELECT * FROM jsonb_each_text('{"a":"x"}'::jsonb);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (key, value) SELECT jsonb_each_text.key AS key, jsonb_each_text.value AS value FROM JSONB_EACH_TEXT(CAST('{"a":"x"}' AS JSONB)) AS jsonb_each_text(key, value)"""
    )


def test__system_function_ts_debug(holder):
    sql = """
    CREATE TABLE public.target (alias VARCHAR, description VARCHAR, token VARCHAR, dictionaries VARCHAR, dictionary VARCHAR, lexemes VARCHAR);

    INSERT INTO public.target
    SELECT * FROM ts_debug('english', 'The quick brown fox');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (alias, description, token, dictionaries, dictionary, lexemes) SELECT ts_debug.alias AS alias, ts_debug.description AS description, ts_debug.token AS token, ts_debug.dictionaries AS dictionaries, ts_debug.dictionary AS dictionary, ts_debug.lexemes AS lexemes FROM TS_DEBUG('english', 'The quick brown fox') AS ts_debug(alias, description, token, dictionaries, dictionary, lexemes)"""
    )


def test__system_function_ts_parse(holder):
    sql = """
    CREATE TABLE public.target (tokid INTEGER, token VARCHAR);

    INSERT INTO public.target
    SELECT * FROM ts_parse('default', 'The quick brown fox');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (tokid, token) SELECT ts_parse.tokid AS tokid, ts_parse.token AS token FROM TS_PARSE('default', 'The quick brown fox') AS ts_parse(tokid, token)"""
    )


def test__system_function_ts_stat(holder):
    sql = """
    CREATE TABLE public.target (word VARCHAR, ndoc INTEGER, nentry INTEGER);

    INSERT INTO public.target
    SELECT * FROM ts_stat('SELECT to_tsvector(''english'', ''fox'')');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (word, ndoc, nentry) SELECT ts_stat.word AS word, ts_stat.ndoc AS ndoc, ts_stat.nentry AS nentry FROM TS_STAT('SELECT to_tsvector(''english'', ''fox'')') AS ts_stat(word, ndoc, nentry)"""
    )


def test__system_function_ts_token_type(holder):
    sql = """
    CREATE TABLE public.target (tokid INTEGER, alias VARCHAR, description VARCHAR);

    INSERT INTO public.target
    SELECT * FROM ts_token_type('default');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[-1].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (tokid, alias, description) SELECT ts_token_type.tokid AS tokid, ts_token_type.alias AS alias, ts_token_type.description AS description FROM TS_TOKEN_TYPE('default') AS ts_token_type(tokid, alias, description)"""
    )


import os
import sys

import pytest
from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.processors.collector.collector import SystemObjectLoader
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__system_objects_lazy_load_pg_am():
    om = mappings.ObjectMapping(dialect=DIALECT, object_loader=SystemObjectLoader(DIALECT))
    assert om.kind_mapping == {}

    columns = om.find(exp.to_table("pg_catalog.pg_am"))

    assert list(columns) == ["oid", "amname", "amhandler", "amtype", "cmax", "cmin", "ctid", "tableoid", "xmax", "xmin"]
    assert columns["amname"] == "NAME"
    assert columns["amtype"] == '"char"'
    assert "table" in om.kind_mapping
    assert om.lookup_table_query(exp.to_table("pg_catalog.pg_am")).kind == "table"


def test__system_objects_lazy_load_unknown_table():
    om = mappings.ObjectMapping(dialect=DIALECT, object_loader=SystemObjectLoader(DIALECT))

    assert om.lookup_table_query(exp.to_table("pg_catalog.not_a_table"), raise_on_missing=False) is None
    assert om.find(exp.to_table("pg_catalog.not_a_table"), raise_on_missing=False) is None


@pytest.mark.skip(reason="todo")
def test__system_objects_postgres(holder):
    sql = """
    INSERT INTO fruit.raw (name)
    SELECT tableowner FROM pg_tables WHERE schemaname = 'public';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    h.generate(sql, dialect="postgres")

    assert h.paths == [
        ["null[NULL]", "column[fruit.b.color]"],
        ["literal[-1]", "column[fruit.b.age]"],
        ["null[NULL]", "column[fruit.a.name]"],
        ["null[NULL]", "column[fruit.a.kind]"],
        ["literal[99]", "column[fruit.a.size]"],
    ]
    assert len(h.nodes) == 10
    assert (
        h.holders[2].transformed.statement.sql() == "INSERT INTO fruit.b (color, age) SELECT NULL AS color, -1 AS age"
    )
