import os
import sys
import pytest

from sqlleaf.exception import SqlLeafException

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import (
    holder, is_subset, DIALECT
)
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

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
    INSERT INTO fruit.processed (age, number)
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


def test__select_fails_unknown_column(holder):
    with pytest.raises(SqlLeafException) as e:
        queries = '''
        INSERT INTO fruit.processed (name)
        SELECT hello
        FROM fruit.raw;
        '''
        h = holder(with_tables=True)
        h.generate(queries, dialect=DIALECT)

    assert e.value.message == "Unknown column 'hello' in query: SELECT hello AS name FROM fruit.raw AS raw"


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
    assert [UpdateQuery, InsertQuery] == list(map(type, queries[0].child_queries))
    assert paths == [
        ['column[fruit.raw.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.kind]', 'column[fruit.processed.label]']
    ]
    assert queries[0].child_queries[0].statement_transformed.sql(dialect=DIALECT) == "INSERT INTO fruit.processed AS t (name) SELECT s.name AS name FROM fruit.raw AS s"
    assert queries[0].child_queries[1].statement_transformed.sql(dialect=DIALECT) == "INSERT INTO fruit.processed AS t (label) SELECT s.kind AS label FROM fruit.raw AS s"

# TODO: test MERGE USING (SELECT ...)
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
    assert [UpdateQuery, InsertQuery] == list(map(type, queries[0].child_queries))
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
    INSERT INTO fruit.processed (name, age)
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


def test__select_window_function(holder):
    queries = '''
    INSERT INTO fruit.processed (amount, age)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY name DESC) AS amount,
        RANK() OVER (PARTITION BY age ORDER BY kind) AS age
    FROM fruit.raw;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()
    assert paths == [
        ['window[RANK()]', 'column[fruit.processed.age]'],
        ['window[ROW_NUMBER()]', 'column[fruit.processed.amount]'],
    ]

def test__select_join_to_self(holder):
    queries = '''
    INSERT INTO fruit.processed (name, age, kind)
    SELECT
        p.name,
        r.age as age,
        color
    FROM fruit.raw r
    INNER JOIN fruit.processed p ON r.name = p.name;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()
    assert paths == [
        ['column[fruit.raw.color]', 'column[fruit.processed.kind]'],
        ['column[fruit.raw.age]', 'column[fruit.processed.age]']
        # Exclude self-referential inserts
    ]

def test__select_assorted(holder):
    queries = '''
    CREATE TABLE anything(name1 VARCHAR, name2 VARCHAR);
    INSERT INTO anything
    SELECT
        ARRAY[1,2,3] as name1,
        INTERVAL '-10.75 MINUTE' as name2;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    assert is_subset(subarr=[
        'literal[{1,2,3} type=ARRAY<INT> node_depth=0 statement=1 select=0 func_depth=0 func_arg=0]',
        'interval["-10.75 MINUTE" type=INTERVAL node_depth=0 statement=1 select=1 func_depth=0 func_arg=0]'
    ], arr=nodes)


# TODO: add JSON_TO_RECORDSET() as a Postgres functions in sqlglot
def test__select_rows_from(holder):
    queries = '''
    INSERT INTO fruit.processed (name, age, kind, amount)
    SELECT *
    FROM ROWS FROM
        (
            unnest(ARRAY['x', 'y']),
            json_to_recordset('[{"a":40,"b":"foo"}]')
                AS (a INTEGER, b TEXT),
            generate_series(1, 3)
        ) AS x (name, age, kind, amount)
    ORDER BY age;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    assert paths == [
        ['literal[{"x","y"}]', 'function[UNNEST()]', 'column[x.name]', 'column[fruit.processed.name]'],
        ['literal["[{"a":40,"b":"foo"}]"]', 'udf[JSON_TO_RECORDSET()]', 'column[_t0.b]', 'column[x.kind]', 'column[fruit.processed.kind]'],
        ['literal["[{"a":40,"b":"foo"}]"]', 'udf[JSON_TO_RECORDSET()]', 'column[_t0.a]', 'column[x.age]', 'column[fruit.processed.age]'],
        ['literal[1]', 'function[EXPLODINGGENERATESERIES()]', 'column[x.amount]', 'column[fruit.processed.amount]'],
        ['literal[3]', 'function[EXPLODINGGENERATESERIES()]', 'column[x.amount]', 'column[fruit.processed.amount]']
    ]
    assert is_subset(subarr=[
        'column[x.age type=UNKNOWN subkind=derived_table]',
        'column[_t0.a type=INT subkind=derived_table]',
    ], arr=nodes)

# TODO: sqlglot parser breaks on 'LATERAL ROWS FROM'
# TODO: support ROWS FROM without table alias


# TODO: test below query
@pytest.mark.skip(reason="todo")
def test__select_lateral(holder):
    queries = '''
    SELECT u.name, task.title
    FROM users u,
    LATERAL get_tasks_for_user(u.id) AS task(title, due_date);
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    assert paths == []


def test__select_union(holder):
    queries = '''
    CREATE TABLE fruit.old (name VARCHAR);

    INSERT INTO fruit.processed (name)
    SELECT name FROM fruit.raw
    UNION
    SELECT name FROM fruit.old;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    edges = h.get_edges()
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()

    assert len(nodes) == 3
    assert len(edges) == 2
    assert paths == [
        ['column[fruit.raw.name]', 'column[fruit.processed.name]'],
        ['column[fruit.old.name]', 'column[fruit.processed.name]']
    ]
