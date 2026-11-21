import os
import sys

import pytest

from sqlleaf import exception
from sqlleaf.models.query import ViewQuery
from tests.new_fixtures import holder as holder

from sqlglot import exp

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__view_materialized(holder):
    sql = """CREATE MATERIALIZED VIEW fruit.one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[-1]", "column[fruit.one.number]"]]
    assert "column[name=number type=INT properties=[kind=view subkind=materialized table=one schema=fruit]]" in h.nodes_full
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
    assert h.queries_transformed[0].statement.sql() == "CREATE MATERIALIZED VIEW fruit.one AS SELECT -1 AS number"


def test__view_no_schema_adds_default_schema(holder):
    sql = """
    CREATE VIEW new AS SELECT 1 AS name;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[1]", "column[public.new.name]"]]
    assert h.queries_transformed[0].statement.sql() == "CREATE VIEW public.new AS SELECT 1 AS name"


def test__view_create_twice_fails(holder):
    with pytest.raises(exception.MappingError) as exc_info:
        sql = """
        CREATE VIEW target AS SELECT 1 AS name;
        CREATE VIEW target AS SELECT 2 AS name;
        """
        holder(sql=sql, dialect=DIALECT)
    assert str(exc_info.value) == "View 'public.target' already exists."


def test__view_create_or_replace_existing_view_succeeds(holder):
    sql = """
    CREATE VIEW v AS SELECT 1 AS name;
    CREATE OR REPLACE VIEW v AS SELECT 2 AS name;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.holders) == 2
    assert all(isinstance(q, ViewQuery) for q in h.queries_original)
    ddl = h.lineage.object_mapping.lookup_table_query(exp.table_("v", "public")).statement.sql(dialect=DIALECT)
    assert ddl == "CREATE OR REPLACE VIEW public.v AS SELECT 2 AS name"

def test__view_create_or_replace_downstream_uses_replaced_definition(holder):
    sql = """
    CREATE VIEW v AS SELECT 1 AS name;
    CREATE OR REPLACE VIEW v AS SELECT 2 AS name;
    CREATE VIEW w AS SELECT name FROM v;
    """
    h = holder(sql=sql, dialect=DIALECT)

    # TODO: design inconsistency: should an unused view have lineage? Or not (like UDFs)?
    assert h.paths == [
        ["literal[1]", "column[public.v.name]", "column[public.w.name]"],
        ["literal[2]", "column[public.v.name]", "column[public.w.name]"]
    ]
    assert h.queries_transformed[1].statement.sql() == "CREATE OR REPLACE VIEW public.v AS SELECT 2 AS name"


view_types = ["", "TEMPORARY"]


@pytest.mark.parametrize("case", view_types)
def test__view_simple(holder, case):
    sql = f"""CREATE {case} VIEW one AS SELECT -1 as number;"""
    h = holder(sql=sql, dialect=DIALECT)

    schema = "pg_temp" if case else "public"
    assert h.paths == [["literal[-1]", f"column[{schema}.one.number]"]]
    subkind = f" subkind={case.lower()}" if case else ""
    assert f"column[name=number type=INT properties=[kind=view{subkind} table=one schema={schema}]]" in h.nodes_full
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
            "column[public.ctas.one]",
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

    assert h.paths == [['literal["a"]', "column[inner1.name]", "column[public.v.name]"]]


def test__view_named_columns(holder):
    sql = """
    CREATE VIEW v(col1, col2) AS
    SELECT name, kind FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.name]", "column[public.v.col1]"], ["column[fruit.raw.kind]", "column[public.v.col2]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__view_updatable_insert_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    INSERT INTO v (a, b) SELECT 1, 2;
    """
    h = holder(sql=sql, dialect="postgres")

    assert h.queries_transformed[-1].statement.sql(dialect="postgres") == "INSERT INTO public.base (a, b) SELECT 1 AS a, 2 AS b"
    assert h.paths == [
        ["literal[1]", "column[public.base.a]", "column[public.v.a]"],
        ["literal[2]", "column[public.base.b]", "column[public.v.b]"],
    ]


def test__view_updatable_update_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    UPDATE v SET a = 5;
    """
    h = holder(sql=sql, dialect="postgres")

    assert h.queries_transformed[-1].statement.sql(dialect="postgres") == "INSERT INTO public.base (a) SELECT 5 AS a FROM public.base AS base"
    assert h.paths == [
        ["column[public.base.b]", "column[public.v.b]"],
        ["literal[5]", "column[public.base.a]", "column[public.v.a]"],
    ]


def test__view_updatable_delete_targets_base_table(holder):
    sql = """
    CREATE TABLE base (a int, b int);
    CREATE VIEW v AS SELECT a, b FROM base;
    DELETE FROM v;
    """
    h = holder(sql=sql, dialect="postgres")

    assert h.queries_transformed[-1].statement.sql(dialect="postgres") == "DELETE FROM public.base"
    assert h.paths == [
        ["column[public.base.a]", "column[public.v.a]"],
        ["column[public.base.b]", "column[public.v.b]"],
    ]


def test__view_updatable_insert_into_read_only_column_fails(holder):
    with pytest.raises(exception.InvalidQueryError, match="Column 'total' of view 'v' is not updatable"):
        sql = """
        CREATE TABLE base (a int, b int);
        CREATE VIEW v AS SELECT a, a + b AS total FROM base;
        INSERT INTO v (total) SELECT 1;
        """
        holder(sql=sql, dialect="postgres")


def test__view_with_aggregate_is_not_updatable(holder):
    with pytest.raises(exception.InvalidQueryError, match="View 'v' is not automatically updatable"):
        sql = """
        CREATE TABLE base (a int, b int);
        CREATE VIEW v AS SELECT a, SUM(b) AS total FROM base GROUP BY a;
        INSERT INTO v (a, total) SELECT 1, 2;
        """
        holder(sql=sql, dialect="postgres")

def test__view_temporary_schema_and_flag(holder):
    sql = """CREATE TEMPORARY VIEW tv AS SELECT 1 AS a;"""
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries_original[0]
    assert isinstance(query, ViewQuery)
    assert query.target_info.expression.sql() == "pg_temp.tv"
    assert query.temporary


def test__view_permanent_not_temporary(holder):
    sql = """CREATE VIEW pv AS SELECT 1 AS a;"""
    h = holder(sql=sql, dialect=DIALECT)

    query = h.queries_original[0]
    assert query.target_info.expression.sql() == "public.pv"
    assert not query.temporary
