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
    CREATE TABLE b.a (ba int);
    CREATE TABLE a.b (ab int);
    CREATE TABLE ctas AS SELECT ab as one FROM a.b;
    CREATE VIEW vie.tab AS SELECT * FROM ctas;
    CREATE VIEW tab.vie AS SELECT ABS(one) AS two FROM vie.tab;
    CREATE VIEW sch.tab.vie AS SELECT two AS three FROM tab.vie
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ['column[a.b.ab]', 'column[ctas.one]', 'column[vie.tab.one]', 'function[ABS()]', 'column[tab.vie.two]', 'column[sch.tab.vie.three]']
    ]
    assert len(nodes) == 6
    assert len(edges) == 5


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
