import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test_insert_ignore(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    INSERT IGNORE INTO users (id, name) VALUES (1, 'Alice');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[1]", "column[users.id]"],
        ['literal["Alice"]', "column[users.name]"]
    ]


def test_insert_set(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    INSERT INTO users SET id = 3, name = 'Charlie';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[3]", "column[users.id]"], ['literal["Charlie"]', "column[users.name]"]]


def test_insert_table(holder):
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
