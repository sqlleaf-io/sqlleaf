import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from sqlleaf.objects.query_types import InsertQuery, UpdateQuery, SelectQuery, MergeQuery
from sqlleaf.exception import SqlLeafException

from tests.new_fixtures import (
    holder, is_subset
)

DIALECT = 'postgres'

def test__cte_simple(holder):
    queries = '''
    WITH cte_names AS (
        SELECT
            lower(age) as age,
            'hello' as name
        FROM fruit.raw r
    )
    INSERT INTO fruit.processed (name, age)
    SELECT
        name,
        age
    FROM cte_names;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    paths = h.get_friendly_paths()

    assert paths == [
        ['literal["hello"]', 'column[cte_names.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.age]', 'function[LOWER()]', 'column[cte_names.age]', 'column[fruit.processed.age]']
    ]


def test__cte_join_same_names(holder):
    queries = '''
    CREATE TABLE fruit.old (kind VARCHAR);

    WITH cte_names AS (
        SELECT
            LOWER(r.kind || o.kind) as kind
        FROM fruit.raw r
        INNER JOIN fruit.old o
        ON r.kind = o.kind
    )
    INSERT INTO fruit.processed (kind)
    SELECT
        kind
    FROM cte_names;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    paths = h.get_friendly_paths()

    assert paths == [
        ['column[fruit.raw.kind]', 'function[DPIPE()]', 'function[LOWER()]', 'column[cte_names.kind]', 'column[fruit.processed.kind]'],
        ['column[fruit.old.kind]', 'function[DPIPE()]', 'function[LOWER()]', 'column[cte_names.kind]', 'column[fruit.processed.kind]']
    ]

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


def test__cte_update_returning_with_old_and_new_aliases(holder):
    queries = '''
    WITH first_cte AS (
        UPDATE fruit.raw
        SET name = 'pear'
        RETURNING old.age as age, new.age as new_age
    )
    UPDATE fruit.processed
    SET age = first_cte.age
    FROM first_cte;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['column[fruit.raw.age]', 'column[first_cte.age]', 'column[fruit.processed.age]'],
        ['literal["pear"]', 'column[fruit.raw.name]'],
    ]
    assert len(nodes) == 5
    assert [UpdateQuery] == list(map(type, queries))
    assert [UpdateQuery] == list(map(type, queries[0].child_queries))


def test__cte_fails_for_returning_unaliased_function(holder):
    with pytest.raises(SqlLeafException) as e:
        queries = '''
        WITH first_cte AS (
            UPDATE fruit.raw
            SET name = 'pear'
            RETURNING upper(name)
        )
        INSERT INTO fruit.processed
        SELECT name
        FROM first_cte;
        '''
        h = holder(with_tables=True)
        h.generate(queries, dialect=DIALECT)

    assert e.value.message == "Non-column expression (UPPER(name)) must have an alias inside RETURNING to prevent ambiguity."


def test__cte_fails_for_returning_ambiguous_aliases(holder):
    with pytest.raises(SqlLeafException) as e:
        queries = '''
        WITH first_cte AS (
            UPDATE fruit.raw
            SET name = 'pear'
            RETURNING old.name, new.name
        )
        INSERT INTO fruit.processed
        SELECT name
        FROM first_cte;
        '''
        h = holder(with_tables=True)
        h.generate(queries, dialect=DIALECT)

    assert e.value.message == "Column reference 'first_cte.name' is ambiguous (2 possible options)"


def test__cte_update_with_two_updates_returning(holder):
    queries = '''
    WITH first_cte AS (
        UPDATE fruit.raw
        SET name = 'pear'
        RETURNING age, old.age as old_age, new.age as new_age
    ),
    second_cte AS (
        UPDATE fruit.raw AS r
        SET name = 'tomato'
        RETURNING *, OLD.*, NEW.*
    )
    UPDATE fruit.processed
    SET age = first_cte.age
    FROM first_cte;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['column[fruit.raw.age]', 'column[first_cte.age]', 'column[fruit.processed.age]'],
        ['literal["pear"]', 'column[fruit.raw.name]'],
        ['literal["tomato"]', 'column[fruit.raw.name]']
    ]
    assert len(nodes) == 6
    assert [UpdateQuery] == list(map(type, queries))
    assert [UpdateQuery, UpdateQuery] == list(map(type, queries[0].child_queries))


def test__cte_merge(holder):
    queries = '''
    WITH cte AS (
        MERGE INTO fruit.processed AS t
        USING fruit.raw AS s
        ON t.kind = s.kind
        WHEN MATCHED THEN
            UPDATE SET name = s.name
        WHEN NOT MATCHED THEN
            INSERT (label) VALUES (s.kind)
        RETURNING merge_action() as action, t.*
    )
    SELECT 1;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['column[fruit.raw.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.kind]', 'column[fruit.processed.label]']
    ]
    assert len(nodes) == 4
    assert [SelectQuery] == list(map(type, queries))
    assert [MergeQuery] == list(map(type, queries[0].child_queries))
    assert [UpdateQuery, InsertQuery] == list(map(type, queries[0].child_queries[0].child_queries))


# TODO: add function merge_action() as system function (not UDF)
def test__cte_merge_returning(holder):
    queries = '''
    CREATE TABLE fruit (name VARCHAR, kind VARCHAR);
    CREATE TABLE drink (name2 VARCHAR, kind2 VARCHAR);
    CREATE TABLE fruit_drink (action VARCHAR, name VARCHAR, kind VARCHAR, name2 VARCHAR, kind2 VARCHAR);

    WITH cte AS (
        MERGE INTO fruit AS t
        USING drink AS s
        ON t.name = s.name2
        WHEN MATCHED THEN
            UPDATE SET name = s.name2
        WHEN NOT MATCHED THEN
            INSERT (kind) VALUES (s.kind2)
        RETURNING merge_action() as action, *
    )
    INSERT INTO fruit_drink
    SELECT *
    FROM cte;
    '''
    h = holder(with_tables=False)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['udf[MERGE_ACTION()]', 'column[cte.action]', 'column[fruit_drink.action]'],
        ['column[drink.name2]', 'column[cte.name2]', 'column[fruit_drink.name2]'],
        ['column[drink.name2]', 'column[fruit.name]', 'column[cte.name]', 'column[fruit_drink.name]'],
        ['column[drink.kind2]', 'column[cte.kind2]', 'column[fruit_drink.kind2]'],
        ['column[drink.kind2]', 'column[fruit.kind]', 'column[cte.kind]', 'column[fruit_drink.kind]']
    ]
    assert queries[3].statement_transformed.sql(dialect=DIALECT) == "WITH cte AS (SELECT MERGE_ACTION() AS action, t.name AS name, t.kind AS kind, s.name2 AS name2, s.kind2 AS kind2 FROM fruit AS t JOIN drink AS s ON s.name2 = t.name) INSERT INTO fruit_drink (action, name, kind, name2, kind2) SELECT cte.action AS action, cte.name AS name, cte.kind AS kind, cte.name2 AS name2, cte.kind2 AS kind2 FROM cte AS cte"


def test__cte_merge_with_update_and_insert(holder):
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

    assert paths == [
        ['column[fruit.raw.name]', 'column[merge_cte.name]', 'column[fruit.processed.name]'],
        ['column[fruit.raw.kind]', 'column[merge_cte.kind]', 'column[fruit.processed.label]']
    ]
    assert len(nodes) == 6
    assert len(queries) == 1
    assert [UpdateQuery, InsertQuery] == list(map(type, queries[0].child_queries))


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

    assert paths == [
        ['column[fruit.raw.kind]', 'column[insert_cte.kind]', 'column[fruit.processed.kind]'],
        ['literal["orange"]', 'column[fruit.raw.name]', 'column[insert_cte.name]', 'column[fruit.processed.name]']
    ]
    assert len(nodes) == 7
    assert [InsertQuery] == list(map(type, queries))
    assert [InsertQuery] == list(map(type, queries[0].child_queries))


def test__cte_insert_conflict_returning(holder):
    queries = '''
    WITH insert_cte AS (
        INSERT INTO fruit.raw (name)
        VALUES ('pear')
        ON CONFLICT (name)
        DO UPDATE SET
            name = LOWER(EXCLUDED.name)
        RETURNING name, 'pear' as kind
    )
    INSERT INTO fruit.processed (name, kind, label)
    SELECT name, kind, 'pear' as label FROM insert_cte;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['literal["pear"]', 'column[insert_cte.kind]', 'column[fruit.processed.kind]'],
        ['literal["pear"]', 'column[fruit.processed.label]'],
        ['literal["pear"]', 'column[fruit.raw.name]', 'column[insert_cte.name]', 'column[fruit.processed.name]'],
        ['literal["pear"]', 'function[LOWER()]', 'column[fruit.raw.name]', 'column[insert_cte.name]', 'column[fruit.processed.name]']
    ]
    assert len(nodes) == 11


def test__cte_insert(holder):
    queries = '''
    WITH insert_cte AS (
        INSERT INTO fruit.raw (name)
        SELECT 'orange' as name
        RETURNING fruit.raw.name, name, *
    ),
    update_cte AS (
        UPDATE fruit.raw AS r
        SET name = 'banana'
    )
    SELECT 1;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['literal["orange"]', 'column[fruit.raw.name]'],
        ['literal["banana"]', 'column[fruit.raw.name]']
    ]
    assert len(nodes) == 3
    assert [SelectQuery] == list(map(type, queries))
    assert [InsertQuery, UpdateQuery] == list(map(type, queries[0].child_queries))


def test__cte_recursive_view(holder):
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
