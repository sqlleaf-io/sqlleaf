import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlglot

from tests.new_fixtures import (
    holder, is_subset, DIALECT
)
from sqlleaf.exception import SqlLeafException
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = 'postgres'



cases = [
    "INSERT INTO fruit.raw VALUES ('yellow', UPPER('banana'));",
    "INSERT INTO fruit.raw (name, kind) VALUES ('yellow', UPPER('banana'));",
    "INSERT INTO fruit.raw (kind, name) VALUES (UPPER('banana'), 'yellow');",
    "INSERT INTO fruit.raw (kind, name) VALUES (UPPER('banana') AS name, 'yellow') AS kind;",
    "INSERT INTO fruit.raw SELECT 'yellow' as name, UPPER('banana') AS kind;",
    "INSERT INTO fruit.raw SELECT 'yellow', UPPER('banana');",
]
@pytest.mark.parametrize("case", cases)
def test__insert_values(holder, case):
    h = holder(with_tables=True)
    h.generate(case, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()
    print()
    assert paths == [
        ['literal["yellow"]', 'column[fruit.raw.name]'],
        ['literal["banana"]', 'function[UPPER()]', 'column[fruit.raw.kind]'],
    ]
    assert [InsertQuery] == list(map(type, queries))


# Not supported by sqlglot: exception - unexpected token 'OVERRIDING'
def test__insert_overriding(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        queries = '''
        INSERT INTO products (id, name) OVERRIDING SYSTEM VALUE VALUES (500, 'Legacy Item');
        '''
        h = holder()
        h.generate(queries, dialect=DIALECT)

    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")
