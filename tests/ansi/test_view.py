import os
import sys

import pytest

from sqlleaf import exception
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = ""


view_types = ["", "TEMPORARY"]


@pytest.mark.parametrize("case", view_types)
def test__view_simple(holder, case):
    sql = f"""CREATE {case} VIEW one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[-1]", "column[one.number]"]]
    subkind = f" subkind={case.lower()}" if case else ""
    assert f"column[name=number type=INT properties=[kind=view{subkind} table=one]]" in h.nodes_full
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
        [
            "column[a.b.ab]",
            "column[ctas.one]",
            "column[vie.tab.one]",
            "function[ABS]",
            "column[tab.vie.two]",
            "column[sch.tab.vie.three]",
        ]
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

    assert h.paths == [["column[fruit.raw.name]", "column[v.col1]"], ["column[fruit.raw.kind]", "column[v.col2]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__view_updatable_insert_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    INSERT INTO v (a, b) SELECT 1, 2;
    """
    h = holder(sql=sql, dialect="")

    assert h.queries_transformed[-1].statement.sql(dialect="") == "INSERT INTO base (a, b) SELECT 1 AS a, 2 AS b"
    assert h.paths == [
        ["literal[1]", "column[base.a]", "column[v.a]"],
        ["literal[2]", "column[base.b]", "column[v.b]"],
    ]


def test__view_updatable_update_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    UPDATE v SET a = 5;
    """
    h = holder(sql=sql, dialect="")

    assert h.queries_transformed[-1].statement.sql(dialect="") == "INSERT INTO base (a) SELECT 5 AS a FROM base AS base"
    assert h.paths == [
        ["column[base.b]", "column[v.b]"],
        ["literal[5]", "column[base.a]", "column[v.a]"],
    ]


def test__view_updatable_delete_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    DELETE FROM v;
    """
    h = holder(sql=sql, dialect="")

    assert h.queries_transformed[-1].statement.sql(dialect="") == "DELETE FROM base"
    assert h.paths == [
        ["column[base.a]", "column[v.a]"],
        ["column[base.b]", "column[v.b]"],
    ]


def test__view_updatable_insert_into_read_only_column_fails(holder):
    with pytest.raises(exception.InvalidQueryError, match="Column 'total' of view 'v' is not updatable"):
        sql = """
        CREATE TABLE base (a int, b int);
        CREATE VIEW v AS SELECT a, a + b AS total FROM base;
        INSERT INTO v (total) SELECT 1;
        """
        holder(sql=sql, dialect="")


def test__view_with_aggregate_is_not_updatable(holder):
    with pytest.raises(exception.InvalidQueryError, match="View 'v' is not automatically updatable"):
        sql = """
        CREATE TABLE base (a int, b int);
        CREATE VIEW v AS SELECT a, SUM(b) AS total FROM base GROUP BY a;
        INSERT INTO v (a, total) SELECT 1, 2;
        """
        holder(sql=sql, dialect="")
