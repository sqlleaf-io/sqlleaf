import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import (
    holder
)
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = 'postgres'


def test__json_one_selector(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT jsonblob -> 'fruits' AS name
    FROM fruit.raw;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()

    assert ['jsonpath[.fruits]', 'column[fruit.processed.name]', 'column[fruit.raw.jsonblob]'] == nodes


def test__json_two_selectors(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT jsonblob ->> 'fruits' -> 'apple' AS name
    FROM fruit.raw;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()

    assert ['jsonpath[.fruits.apple]', 'column[fruit.processed.name]', 'column[fruit.raw.jsonblob]'] == nodes
