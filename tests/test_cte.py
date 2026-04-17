import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from sqlleaf.objects.query_types import InsertQuery, UpdateQuery, SelectQuery

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
    INSERT INTO fruit.processed (name, name1, name2, name3)
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
    assert [InsertQuery] == list(map(type, queries))


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
        'column[cte1.name type=INT subkind=cte statement=0]',
        'column[cte1.name type=INT subkind=cte statement=1]',
    ], arr=nodes)
    assert [InsertQuery, InsertQuery] == list(map(type, queries))


def test__cte_chained(holder):
    queries = '''
    WITH cte_one AS (
        SELECT name FROM fruit.raw
    ),
    cte_two AS (
        SELECT * FROM cte_one
    )
    INSERT INTO fruit.processed
    SELECT * FROM cte_two;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()

    assert paths == [
        ['column[fruit.raw.name]', 'column[cte_one.name]', 'column[cte_two.name]', 'column[fruit.processed.name]']
    ]


def test__cte_nested(holder):
    queries = '''
    WITH outer_cte AS (
        WITH inner_cte AS (
            SELECT name FROM fruit.raw
        )
        SELECT * FROM inner_cte
    )
    INSERT INTO fruit.processed
    SELECT * FROM outer_cte;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()

    assert paths == [
        ['column[fruit.raw.name]', 'column[inner_cte.name]', 'column[outer_cte.name]', 'column[fruit.processed.name]']
    ]


def test__cte_insert_returning(holder):
    queries = '''
    WITH insert_cte AS (
        INSERT INTO fruit.raw as r (name)
        SELECT 'orange' as name
        RETURNING name, kind
    )
    INSERT INTO fruit.processed (name, kind)
    SELECT name, kind FROM insert_cte;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert len(nodes) == 7
    assert paths == [
        ['column[fruit.raw.kind]', 'column[insert_cte.kind]', 'column[fruit.processed.kind]'],
        ['literal["orange"]', 'column[fruit.raw.name]', 'column[insert_cte.name]', 'column[fruit.processed.name]']
    ]
    assert [InsertQuery] == list(map(type, queries))
    assert [InsertQuery] == list(map(type, queries[0].child_queries))


def test__cte_insert(holder):
    queries = '''
    WITH insert_cte AS (
        INSERT INTO fruit.raw (name)
        SELECT 'orange' as name
        RETURNING fruit.raw.name, name, *
    ),
    update_cte AS (
        UPDATE fruit.raw
        SET name = 'banana'
    )
    SELECT 1;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert len(nodes) == 3
    assert paths == [
        ['literal["orange"]', 'column[fruit.raw.name]'],
        ['literal["banana"]', 'column[fruit.raw.name]']
    ]
    assert [SelectQuery] == list(map(type, queries))
    assert [InsertQuery, UpdateQuery] == list(map(type, queries[0].child_queries))


def test__view_with_recursive_cte(holder):
    queries = """
    WITH RECURSIVE numbers AS (
        SELECT 1 AS n
        UNION ALL
        SELECT n + 1 AS n
        FROM numbers
        WHERE n < 5
    )
    INSERT INTO fruit.processed (age)
    SELECT n AS age FROM numbers;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect='postgres')
    nodes = h.get_full_node_names()
    paths = h.get_full_paths()

    assert paths == [
        [
            'literal[1 type=INT node_depth=1 statement=0 select=0 func_depth=0 func_arg=0]',
            'column[numbers.n type=INT subkind=cte member=anchor statement=0]',
            'column[fruit.processed.age type=INT subkind=table]'
         ],
        [
            'literal[1 type=INT node_depth=1 statement=0 select=0 func_depth=0 func_arg=0]',
            'column[numbers.n type=INT subkind=cte member=anchor statement=0]',
            'function[ADD() type=INT node_depth=1 statement=0 select=0 func_depth=0 func_arg=0]',
            'column[numbers.n type=INT subkind=cte member=recursive statement=0]',
            'column[fruit.processed.age type=INT subkind=table]'
         ],
        [
            'literal[1 type=INT node_depth=1 statement=0 select=0 func_depth=1 func_arg=1]',
            'function[ADD() type=INT node_depth=1 statement=0 select=0 func_depth=0 func_arg=0]',
            'column[numbers.n type=INT subkind=cte member=recursive statement=0]',
            'column[fruit.processed.age type=INT subkind=table]'
         ]
    ]
