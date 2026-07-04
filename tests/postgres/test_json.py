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

    assert h.paths == [
        [
            "column[fruit.raw.jsonblob]",
            "jsonpath[.fruits]",
            "column[fruit.processed.name]",
        ]
    ]
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


# FIELDS
