import os
import sys

import pytest
from sqlglot.errors import ParseError

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__json_one_selector(holder):
    sql = """
    INSERT INTO fruit.processed
    SELECT jsonblob -> 'fruits' AS name
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.jsonblob]", "jsonpath[.fruits]", "column[fruit.processed.name]"]]
    assert h.nodes_full == [
        "jsonpath[name=.fruits properties=[depth=1]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=jsonblob type=JSONB properties=[kind=table table=raw schema=fruit]]",
    ]


def test__json_two_selectors(holder):
    sql = """
    INSERT INTO fruit.processed
    SELECT jsonblob ->> 'fruits' -> 'apple' AS name
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.jsonblob]", "jsonpath[.fruits.apple]", "column[fruit.processed.name]"]]
    assert h.nodes_full == [
        "jsonpath[name=.fruits.apple properties=[depth=2]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=jsonblob type=JSONB properties=[kind=table table=raw schema=fruit]]",
    ]


def test__json_one_selector_integer(holder):
    sql = """
    INSERT INTO fruit.processed
    SELECT jsonblob ->> 2 AS name
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.jsonblob]", "jsonpath[2]", "column[fruit.processed.name]"]]
    assert h.nodes_full == [
        "jsonpath[name=2 properties=[depth=1]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=jsonblob type=JSONB properties=[kind=table table=raw schema=fruit]]",
    ]


# TODO: support subscripting
def test__json_subscript_nested(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (email text);

    INSERT INTO public.target
    SELECT data['user']['email'] AS email
    FROM public.source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[public.source.data]",
            # "jsonpath[.user.email]",
            "column[public.target.email]",
        ]
    ]
    assert h.nodes_full == [
        # "jsonpath[name=.user.email properties=[depth=2]]",
        "column[name=data type=JSONB properties=[kind=table table=source schema=public]]",
        "column[name=email type=TEXT properties=[kind=table table=target schema=public]]",
    ]


# TODO: support subscripting
#   UPDATE target SET data['status'] = '"shipped"';
#   ->
#   INSERT INTO public.target (data) SELECT '{"status": "shipped"}'
# def test__json_subscript_update(holder):
#     sql = """
#     CREATE TABLE target (data jsonb);
#
#     UPDATE target SET data['status'] = '"shipped"';
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     assert h.paths == [['literal["shipped"]', "column[target.data]"]]


def test__json_each_text(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_each_text('{"a":"x"}'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (first, last) SELECT json_each_text.key AS first, json_each_text.value AS last FROM JSON_EACH_TEXT(CAST('{"a":"x"}' AS JSON)) AS json_each_text(key, value)"""
    )


def test__json_each_text_alias(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_each_text('{"a":"x"}') AS t(k, v);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (first, last) SELECT t.k AS first, t.v AS last FROM JSON_EACH_TEXT('{"a":"x"}') AS t(k, v)"""
    )
    assert h.nodes_full == [
        'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
        "function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "column[name=k type=UNKNOWN properties=[kind=udtf table=t]]",
        "column[name=v type=UNKNOWN properties=[kind=udtf table=t]]",
        "column[name=first type=VARCHAR properties=[kind=table table=target schema=public]]",
        "column[name=last type=VARCHAR properties=[kind=table table=target schema=public]]",
    ]
    assert h.paths_full == [
        [
            'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
            "function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
            "column[name=k type=UNKNOWN properties=[kind=udtf table=t]]",
            "column[name=first type=VARCHAR properties=[kind=table table=target schema=public]]",
        ],
        [
            'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
            "function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
            "column[name=v type=UNKNOWN properties=[kind=udtf table=t]]",
            "column[name=last type=VARCHAR properties=[kind=table table=target schema=public]]",
        ],
        [
            'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
            "function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
            "column[name=k type=UNKNOWN properties=[kind=udtf table=t]]",
            "column[name=first type=VARCHAR properties=[kind=table table=target schema=public]]",
        ],
        [
            'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
            "function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
            "column[name=v type=UNKNOWN properties=[kind=udtf table=t]]",
            "column[name=last type=VARCHAR properties=[kind=table table=target schema=public]]",
        ],
    ]


def test__json_table(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (name VARCHAR);

    INSERT INTO public.target
    SELECT jt.name
    FROM public.source, JSON_TABLE(
        public.source.data,
        '$' COLUMNS (
            name VARCHAR PATH '$.name'
        )
    ) AS jt;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[public.source.data]",
            "jsonpath[$]",
            "jsonpath[$.name]",
            "column[jt.name]",
            "column[public.target.name]",
        ]
    ]


def test__json_table_literal(holder):
    sql = """
    CREATE TABLE target (a INT, b INT, c VARCHAR);

    INSERT INTO public.target
    SELECT jt.*
    FROM JSON_TABLE(
      '[{"id": 1, "name": "Alice"}]',
      '$[*]'
      COLUMNS (
        row_num FOR ORDINALITY,
        user_id int PATH '$.id',
        user_name text PATH '$.name'
      )
    ) AS jt;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["series[]", "column[jt.row_num]", "column[public.target.a]"],
        [
            'literal["[{"id": 1, "name": "Alice"}]"]',
            "jsonpath[$[*]]",
            "jsonpath[$.id]",
            "column[jt.user_id]",
            "column[public.target.b]",
        ],
        [
            'literal["[{"id": 1, "name": "Alice"}]"]',
            "jsonpath[$[*]]",
            "jsonpath[$.name]",
            "column[jt.user_name]",
            "column[public.target.c]",
        ],
    ]


def test__json_table_default_path(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (user_id INT);

    INSERT INTO public.target
    SELECT jt.user_id
    FROM public.source, JSON_TABLE(public.source.data, '$[*]' COLUMNS (user_id INT)) AS jt;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[public.source.data]",
            "jsonpath[$[*]]",
            'jsonpath[$."user_id"]',
            "column[jt.user_id]",
            "column[public.target.user_id]",
        ]
    ]


def test__json_table_exists_column(holder):
    with pytest.raises(ParseError) as e:
        sql = """
        CREATE TABLE source (data jsonb);
        CREATE TABLE target (has_flag BOOLEAN);

        INSERT INTO public.target
        SELECT jt.has_flag
        FROM public.source, JSON_TABLE(public.source.data, '$[*]' COLUMNS (has_flag BOOLEAN EXISTS PATH '$.flag')) AS jt;
        """
        h = holder(sql=sql, dialect=DIALECT)
        assert h.paths == [
            ["column[public.source.data]", "jsonpath[$.flag]", "column[jt.has_flag]", "column[public.target.has_flag]"]
        ]
    assert e.value.args[0].startswith("Invalid expression / Unexpected token. Line 7, Col: 38.")


def test__json_table_format_json_column(holder):
    sql = """
    CREATE TABLE source (payload jsonb);
    CREATE TABLE target (data JSONB);

    INSERT INTO public.target
    SELECT jt.data
    FROM public.source, JSON_TABLE(public.source.payload, '$[*]' COLUMNS (data JSONB FORMAT JSON PATH '$.data')) AS jt;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[public.source.payload]",
            "jsonpath[$[*]]",
            "jsonpath[$.data]",
            "column[jt.data]",
            "column[public.target.data]",
        ]
    ]


def test__json_table_column_on_empty_error(holder):
    with pytest.raises(ParseError) as e:
        sql = """
        CREATE TABLE source (data jsonb);
        CREATE TABLE target (name VARCHAR);

        INSERT INTO public.target
        SELECT jt.name
        FROM public.source, JSON_TABLE(public.source.data, '$[*]' COLUMNS (name VARCHAR PATH '$.name' DEFAULT 'unknown' ON EMPTY NULL ON ERROR)) AS jt;
        """
        h = holder(sql=sql, dialect=DIALECT)
        assert h.paths == [
            ["column[public.source.data]", "jsonpath[$.name]", "column[jt.name]", "column[public.target.name]"],
            ['literal["unknown"]', "column[jt.name]", "column[public.target.name]"],
        ]
    assert e.value.args[0].startswith("Invalid expression / Unexpected token. Line 7, Col: 38.")


def test__json_table_nested_path(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (sku VARCHAR);

    INSERT INTO public.target
    SELECT jt.sku
    FROM public.source, JSON_TABLE(
        public.source.data, '$[*]'
        COLUMNS (
            NESTED PATH '$.items[*]'
                COLUMNS (
                    sku VARCHAR PATH '$.sku'
                )
        )
    ) AS jt;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[public.source.data]",
            "jsonpath[$[*]]",
            "jsonpath[$.items[*]]",
            "jsonpath[$.sku]",
            "column[jt.sku]",
            "column[public.target.sku]",
        ]
    ]


def test__json_each_text_alias_no_columns(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    INSERT INTO public.target
    SELECT * FROM json_each_text('{"a":"x"}') AS t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO public.target (first, last) SELECT t.key AS first, t.value AS last FROM JSON_EACH_TEXT('{"a":"x"}') AS t(key, value)"""
    )
