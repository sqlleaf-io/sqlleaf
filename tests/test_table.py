import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlleaf import structs

from tests.new_fixtures import (
    holder
)

DIALECT = 'postgres'

def test__table_like_table(holder):
    queries = '''
    CREATE TABLE fruit.a (name varchar, age int default 42);
    CREATE TABLE fruit.b_like_a (label varchar) LIKE fruit.a INCLUDING ALL;
    CREATE TABLE fruit.c (label varchar, name varchar, age int);

    INSERT INTO fruit.c SELECT * FROM fruit.b_like_a;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert len(nodes) == 6
    assert len(edges) == 3
    assert paths == [
        ['column[fruit.b_like_a.label]', 'column[fruit.c.label]'],
        ['column[fruit.b_like_a.name]', 'column[fruit.c.name]'],
        ['column[fruit.b_like_a.age]', 'column[fruit.c.age]']
    ]


def test__table_with_default_columns(holder):
    queries = '''
    CREATE TABLE fruit (name varchar, size int default 1, age int default 42);

    INSERT INTO fruit
    SELECT 'apple' as name, 10 as size;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ['literal["apple"]', 'column[fruit.name]'],
        ['literal[1]', 'column[fruit.size]'],
        ['literal[10]', 'column[fruit.size]'],
        ['literal[42]', 'column[fruit.age]']
    ]


@pytest.mark.skip(reason="todo")
def test__table_inherits_table(holder):
    queries = '''
    CREATE TABLE fruit.a (name varchar, age int default 42);
    CREATE TABLE fruit.b_inherits_a (label varchar) INHERITS (fruit.a);
    CREATE TABLE fruit.c (name varchar);

    INSERT INTO fruit.c SELECT name FROM fruit.a;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)

    # expect: fruit.a.name -> fruit.processed.name
    # expect: fruit.b_inherits_a.name -> fruit.processed.name

view_types = ['', 'MATERIALIZED']
@pytest.mark.parametrize("case", view_types)
def test__view_simple(holder, case):
    queries = f'''CREATE {case} VIEW one AS SELECT -1 as number;'''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()

    assert paths == [['literal[-1]', 'column[one.number]']]


def test__views_and_ctas_with_every_hierarchy(holder):
    queries = '''
    CREATE TABLE base (one int);
    CREATE TABLE ctas AS SELECT one FROM base;
    CREATE VIEW vie AS SELECT * FROM ctas;
    CREATE VIEW tab.vie AS SELECT one AS two FROM vie;
    CREATE VIEW sch.tab.vie AS SELECT two AS three FROM tab.vie;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert len(nodes) == 5
    assert len(edges) == 4
    assert paths == [
        ['column[base.one]', 'column[ctas.one]', 'column[vie.one]', 'column[tab.vie.two]', 'column[sch.tab.vie.three]']
    ]


def test__view_with_cte(holder):
    queries = '''
    CREATE VIEW v AS
    WITH inner1 AS (
        SELECT 'a' as name
    )
    SELECT * FROM inner1;
    '''
    h = holder()
    h.generate(queries, dialect='postgres')
    paths = h.get_friendly_paths()

    assert paths == [
        ['literal["a"]', 'column[inner1.name]', 'column[v.name]']
    ]



# TODO: test views using interchanging schema/view name to see if conflicts in mapping hierarchy
# create view par.chi ...
# create view chi.par ...
# create view par
# create view chi

def test__simple_sequence(holder):
    queries = '''
    CREATE SEQUENCE serial START 101;
    INSERT INTO fruit.raw (age) SELECT nextval('serial') as age;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert paths == [['sequence[serial]', 'column[fruit.raw.age]']]
    assert [structs.SequenceQuery, structs.InsertQuery] == list(map(type, queries))
