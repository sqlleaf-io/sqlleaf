import os
import sys

import sqlglot

from sqlleaf.models.query import TableQuery, ReplaceQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test_replace(holder):
    sql = """
    CREATE TABLE users (id INT, name VARCHAR(255));
    REPLACE INTO users (id, name) VALUES (1, 'Alice');
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.query_types == [TableQuery, ReplaceQuery]

    assert h.paths == [
        ["literal[1]", "column[users.id]"],
        ['literal["Alice"]', "column[users.name]"]
    ]


def test_replace_unsupported(holder):
    sql = """
    REPLACE INTO users (id, name) VALUES (1, 'Alice');
    """
    s = sqlglot.parse_one(sql, dialect=DIALECT)
    assert type(s) == sqlglot.exp.Command
