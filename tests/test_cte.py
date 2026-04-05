import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from sqlleaf import structs

from tests.new_fixtures import (
    holder, is_subset
)

DIALECT = 'postgres'

def test__cte_same_functions_different_levels(holder):
    queries = '''
    WITH cte_names AS (
        SELECT 
            'hello' as not_used,
            'a' as a_name,
            LOWER('a') as a_name1,
            1 as ignored
    )
    INSERT INTO fruit.processed
    SELECT
        'a' as name,
        LOWER('a') as name1,
        LOWER(cte_names.a_name) as name2,
        LOWER(LOWER(cte_names.a_name1)) as name3
    FROM cte_names;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()

    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['literal["a"]', 'column[fruit.processed.name]'],
        ['literal["a"]', 'function[LOWER()]', 'column[fruit.processed.name1]'],
        ['literal["a"]', 'column[cte_names.a_name]', 'function[LOWER()]', 'column[fruit.processed.name2]'],
        ['literal["a"]', 'function[LOWER()]', 'column[cte_names.a_name1]', 'function[LOWER()]', 'function[LOWER()]', 'column[fruit.processed.name3]']
    ]


def test__cte_two_identical(holder):
    queries = '''
    WITH cte1 AS (SELECT 'a' as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;

    WITH cte1 AS (SELECT 'a' as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['literal["a"]', 'column[cte1.name]', 'column[fruit.processed.name]']
    ]
    assert [structs.InsertQuery] == list(map(type, queries))


def test__cte_two_same_name_different_query(holder):
    queries = '''
    WITH cte1 AS (SELECT 1 as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;

    WITH cte1 AS (SELECT 2 as name)
    INSERT INTO fruit.raw
    SELECT c.name as name
    FROM cte1 c;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['literal[1]', 'column[cte1.name]', 'column[fruit.processed.name]'],
        ['literal[2]', 'column[cte1.name]', 'column[fruit.raw.name]']
    ]
    assert is_subset(subarr=[
        'column[cte1.name type=INT statement=0 kind=cte]',
        'column[cte1.name type=INT statement=1 kind=cte]',
    ], arr=nodes)
    assert [structs.InsertQuery, structs.InsertQuery] == list(map(type, queries))
