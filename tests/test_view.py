import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

DIALECT = "postgres"


view_types = ["", "TEMPORARY", "MATERIALIZED"]


@pytest.mark.parametrize("case", view_types)
def test__view_simple(holder, case):
    sql = f"""CREATE {case} VIEW one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[-1]", "column[one.number]"]]
    subkind = f" subkind={case.lower()}" if case else ""
    assert f'column[one.number type=INT kind=view{subkind}]' in h.nodes_full
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__views_and_ctas_with_every_hierarchy(holder):
    sql = """
    CREATE TABLE b.a (ba int);
    CREATE TABLE a.b (ab int);
    CREATE TABLE ctas AS SELECT ab as one FROM a.b;
    CREATE VIEW vie.tab AS SELECT * FROM ctas;
    CREATE VIEW tab.vie AS SELECT ABS(one) AS two FROM vie.tab;
    CREATE VIEW sch.tab.vie AS SELECT two AS three FROM tab.vie
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[a.b.ab]", "column[ctas.one]", "column[vie.tab.one]", "function[ABS]", "column[tab.vie.two]", "column[sch.tab.vie.three]"]
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5


def test__view_with_cte(holder):
    sql = """
    CREATE VIEW v AS
    WITH inner1 AS (
        SELECT 'a' as name
    )
    SELECT * FROM inner1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['literal["a"]', "column[inner1.name]", "column[v.name]"]]


def test__view_named_columns(holder):
    sql = """
    CREATE VIEW v(col1, col2) AS
    SELECT name, kind FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['column[fruit.raw.name]', 'column[v.col1]'],
        ['column[fruit.raw.kind]', 'column[v.col2]']
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
