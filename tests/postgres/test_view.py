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
