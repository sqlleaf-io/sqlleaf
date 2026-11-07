import os
import sys

import pytest
from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.processors.collector.collector import SystemObjectLoader
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__system_table_lazy_load_pg_am():
    om = mappings.ObjectMapping(dialect=DIALECT, object_loader=SystemObjectLoader(DIALECT))
    assert om.kind_mapping == {}

    columns = om.find(exp.to_table("pg_catalog.pg_am"))

    assert list(columns) == ["oid", "amname", "amhandler", "amtype", "cmax", "cmin", "ctid", "tableoid", "xmax", "xmin"]
    assert columns["amname"] == "NAME"
    assert columns["amtype"] == '"char"'
    assert "table" in om.kind_mapping
    assert om.lookup_table_query(exp.to_table("pg_catalog.pg_am")).kind == "table"


def test__system_table_lazy_load_unknown_table():
    om = mappings.ObjectMapping(dialect=DIALECT, object_loader=SystemObjectLoader(DIALECT))

    assert om.lookup_table_query(exp.to_table("pg_catalog.not_a_table"), raise_on_missing=False) is None
    assert om.find(exp.to_table("pg_catalog.not_a_table"), raise_on_missing=False) is None


@pytest.mark.skip(reason="todo")
def test__system_tables_postgres(holder):
    sql = """
    INSERT INTO fruit.raw (name)
    SELECT tableowner FROM pg_tables WHERE schemaname = 'public';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    h.generate(sql, dialect="postgres")

    assert h.paths == [
        ["null[NULL]", "column[fruit.b.color]"],
        ["literal[-1]", "column[fruit.b.age]"],
        ["null[NULL]", "column[fruit.a.name]"],
        ["null[NULL]", "column[fruit.a.kind]"],
        ["literal[99]", "column[fruit.a.size]"],
    ]
    assert len(h.nodes) == 10
    assert (
        h.holders[2].transformed.statement.sql() == "INSERT INTO fruit.b (color, age) SELECT NULL AS color, -1 AS age"
    )
