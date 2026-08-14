import os
import sys

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

    INSERT INTO target
    SELECT data['user']['email'] AS email
    FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[source.data]",
            # "jsonpath[.user.email]",
            "column[target.email]",
        ]
    ]
    assert h.nodes_full == [
        # "jsonpath[name=.user.email properties=[depth=2]]",
        "column[name=data type=JSONB properties=[kind=table table=source]]",
        "column[name=email type=TEXT properties=[kind=table table=target]]",
    ]


# TODO: support subscripting
#   UPDATE target SET data['status'] = '"shipped"';
#   ->
#   INSERT INTO target (data) SELECT '{"status": "shipped"}'
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

    INSERT INTO target
    SELECT * FROM json_each_text('{"a":"x"}'::json);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO target (first, last) SELECT json_each_text.key AS first, json_each_text.value AS last FROM JSON_EACH_TEXT(CAST('{"a":"x"}' AS JSON)) AS json_each_text(key, value)"""
    )


def test__json_each_text_alias(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    INSERT INTO target
    SELECT * FROM json_each_text('{"a":"x"}') AS t(k, v);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO target (first, last) SELECT t.k AS first, t.v AS last FROM JSON_EACH_TEXT('{"a":"x"}') AS t(k, v)"""
    )
    assert h.nodes_full == [
         'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
         'function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
         'column[name=k type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=v type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=first type=VARCHAR properties=[kind=table table=target]]',
         'column[name=last type=VARCHAR properties=[kind=table table=target]]',
     ]
    assert h.paths_full == [
     [
         'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
         'function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
         'column[name=k type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=first type=VARCHAR properties=[kind=table table=target]]',
     ],
     [
         'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
         'function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
         'column[name=v type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=last type=VARCHAR properties=[kind=table table=target]]',
     ],
     [
         'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
         'function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
         'column[name=k type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=first type=VARCHAR properties=[kind=table table=target]]',
     ],
     [
         'literal[name="{"a":"x"}" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=1 func_arg=0]]',
         'function[name=JSON_EACH_TEXT type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
         'column[name=v type=UNKNOWN properties=[kind=udtf table=t]]',
         'column[name=last type=VARCHAR properties=[kind=table table=target]]',
     ],
 ]


def test__json_each_text_alias_no_columns(holder):
    sql = """
    CREATE TABLE source (data jsonb);
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    INSERT INTO target
    SELECT * FROM json_each_text('{"a":"x"}') AS t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == """INSERT INTO target (first, last) SELECT t.key AS first, t.value AS last FROM JSON_EACH_TEXT('{"a":"x"}') AS t(key, value)"""
    )
