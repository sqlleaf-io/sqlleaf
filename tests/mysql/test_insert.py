import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


# TODO: bug in the cycle logic
# def test__insert_on_duplicate_key_update(holder):
#     sql = """
#     CREATE TABLE stats (id INT, count INT);
#     INSERT INTO stats (id, count) VALUES (1, 1)
#     ON DUPLICATE KEY
#     UPDATE count = count + 1;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     h.lineage.print_tree()
#
#     assert h.nodes_full == [
#          'literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
#          'literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]',
#          'literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=1 func_arg=1]]',
#          'function[name=ADD type=INT position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]',
#          'column[name=count type=INT properties=[kind=table table=stats]]',
#          'column[name=id type=INT properties=[kind=table table=stats]]',
#      ]
#     assert h.paths == [
#         ["literal[1]", "column[stats.id]"],
#         ["literal[1]", "column[stats.count]", "function[ADD]", "column[stats.count]"],
#         ["literal[1]", "function[ADD]", "column[stats.count]", "function[ADD]"],
#     ]


def test__insert_ignore(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    INSERT IGNORE INTO users (id, name) VALUES (1, 'Alice');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[1]", "column[users.id]"], ['literal["Alice"]', "column[users.name]"]]


def test__insert_set(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    INSERT INTO users SET id = 3, name = 'Charlie';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO users (id, name) SELECT 3 AS id, 'Charlie' AS name"
    )
    assert h.paths == [["literal[3]", "column[users.id]"], ['literal["Charlie"]', "column[users.name]"]]


def test__insert_as_alias(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    INSERT INTO users (id, name) VALUES (1, 'Alice') AS new_row ON DUPLICATE KEY UPDATE name = new_row.name;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[1]", "column[users.id]"],
        ['literal["Alice"]', "column[users.name]"],
        ['literal["Alice"]', "column[users.name]"],
    ]


def test__insert_select_on_duplicate_key_update(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255), kind int);
    CREATE TABLE other_users (id INT, name VARCHAR(255));
    INSERT INTO users (id, name) SELECT id, UPPER(name) FROM other_users ON DUPLICATE KEY UPDATE name = VALUES(name);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[other_users.id]", "column[users.id]"],
        ["column[other_users.name]", "function[UPPER]", "column[users.name]"],
        ["column[other_users.name]", "function[UPPER]", "column[users.name]"],
    ]


def test__insert_select_on_duplicate_key_update_unnamed_columns(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255), kind int);
    CREATE TABLE other_users (id INT, name VARCHAR(255));
    INSERT INTO users SELECT id, UPPER(name) FROM other_users ON DUPLICATE KEY UPDATE name = VALUES(name);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[other_users.id]", "column[users.id]"],
        ["column[other_users.name]", "function[UPPER]", "column[users.name]"],
        ["column[other_users.name]", "function[UPPER]", "column[users.name]"],
    ]


def test__insert_select_on_duplicate_key_invalid_column_fails(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        CREATE TABLE users (id INT, name VARCHAR(255), kind int);
        CREATE TABLE other_users (id INT, name VARCHAR(255));
        INSERT INTO users (id, name) SELECT id, UPPER(name) FROM other_users ON DUPLICATE KEY UPDATE name = VALUES(kind);
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith(
        "Column 'kind' does not exist in the expression list or the columns for table 'users'"
    )


def test__insert_table(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    CREATE TABLE other_users (id INT, name VARCHAR(255));
    INSERT INTO users TABLE other_users;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[other_users.id]", "column[users.id]"],
        ["column[other_users.name]", "column[users.name]"],
    ]
