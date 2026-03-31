import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlleaf import structs

from tests.new_fixtures import (
    holder
)

DIALECT = 'postgres'

# TODO: unnest([N...]) returns N columns named 'unnest', but sqlglot calls them 'offset'
#  We need to throw an error if unnest() is called without specific column selection.
#  We also need to undo sqlglot's column renaming of {col} => {col}.offset
"""
SELECT * FROM unnest(ARRAY['apple', 'banana']);                             -- Invalid
SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY;             -- Invalid
SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY AS t(a,b);   -- Valid        but sqlglot sets fruit => fruit.offset
SELECT fruit FROM unnest(ARRAY['apple', 'banana']);                         -- Valid        but sqlglot sets fruit => fruit.offset
"""

@pytest.mark.skip(reason="todo")
def test__select_with_ordinality(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY AS t(name, age);
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()



def test__case_simple(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT 
        CASE WHEN name = 'John' THEN 1 ELSE 2 END AS age,
        CASE WHEN name = 'John' THEN 1 END AS number
    FROM fruit.raw
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert len(nodes) == 6
    assert len(edges) == 4
    assert paths == [
        ['literal[2]', 'column[fruit.processed.age]'],
        ['literal[1]', 'column[fruit.processed.age]'],
        ['null[NULL]', 'column[fruit.processed.number]'],
        ['literal[1]', 'column[fruit.processed.number]']
    ]


def test__merge_simple_update_and_insert(holder):
    queries = '''
    MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()

    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert len(nodes) == 4
    assert len(queries) == 1
    assert [structs.UpdateQuery, structs.InsertQuery] == list(map(type, queries[0].child_queries))
    assert paths == [
        ['column[fruit.raw.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.kind]', 'column[fruit.processed.label]']
    ]

# TODO: test two merge queries that have an identical inner query
#  expect: the two inner queries are identical (and preserved), but they have different parents

def test__merge_simple_update_and_insert_with_cte(holder):
    queries = '''
    WITH merge_cte AS ( 
        SELECT kind, name
        FROM fruit.raw
    )
    MERGE INTO fruit.processed AS t
    USING merge_cte AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert len(nodes) == 6
    assert len(queries) == 1
    assert [structs.UpdateQuery, structs.InsertQuery] == list(map(type, queries[0].child_queries))
    assert paths == [
        ['column[fruit.raw.name]', 'column[merge_cte.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.kind]', 'column[merge_cte.kind]', 'column[fruit.processed.label]']
    ]


tests = [
    ('-10', 'literal'),
    ('10', 'literal'),
    ('TRUE', 'literal'),
    ('NULL', 'null',),
    ('LOCALTIME()', 'function'),
    ('MY.FUNC()', 'udf'),
]

@pytest.mark.parametrize("case", tests)
def test__select_value_twice(case, holder):
    value, kind = case
    queries = f'''
    INSERT INTO fruit.processed
    SELECT {value} as name, {value} as age;
    '''
    print(queries)
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    paths = h.get_friendly_paths()

    assert len(nodes) == 4
    assert paths == [
        [f'{kind}[{value}]', 'column[fruit.processed.name]'],
        [f'{kind}[{value}]', 'column[fruit.processed.age]'],
    ]

# TODO: select_query_twice
# TODO: select_query_twice, but slightly different second

# Circular inserts, CTEs, etc

def test__select_window_function(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT 
        ROW_NUMBER() OVER (ORDER BY created_at DESC) AS amount,
        RANK() OVER (PARTITION BY age ORDER BY updated_at) AS age
    FROM fruit.raw;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()
    assert paths == [
        ['window[RANK()]', 'column[fruit.processed.age]'],
        ['window[ROW_NUMBER()]', 'column[fruit.processed.amount]'],
    ]

def test__select_join(holder):
    queries = '''
    INSERT INTO fruit.processed
    SELECT
        p.name,
        r.age as age
    FROM fruit.raw r
    INNER JOIN fruit.processed p ON r.name = p.name;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()
    assert paths == [
        ['column[fruit.raw.age]', 'column[fruit.processed.age]']
        # Exclude self-referential inserts
    ]
