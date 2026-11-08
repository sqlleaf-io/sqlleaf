from sqlleaf.dialects.loader import get_object_ddl
from tests.new_fixtures import holder as holder

DIALECT = "postgres"
SQL = get_object_ddl("pg_catalog", "pg_policies", DIALECT)


def test__system_view_target_has_no_lineage(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.nodes == []
    assert h.edges == []
    assert h.paths == []


def test__insert_select_from_system_view_has_lineage(holder):
    sql = SQL + (
        """
    CREATE TABLE public.archive (schemaname VARCHAR, tablename VARCHAR);
    INSERT INTO public.archive (schemaname, tablename) SELECT schemaname, tablename FROM pg_catalog.pg_policies;
    """
    )
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[pg_catalog.pg_policies.schemaname]", "column[public.archive.schemaname]"],
        ["column[pg_catalog.pg_policies.tablename]", "column[public.archive.tablename]"],
    ]
