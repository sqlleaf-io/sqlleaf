import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__external_view(holder):
    sql = """
    CREATE EXTERNAL VIEW fruit.ext_view
    AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.ext_view.name]"],
        ["column[fruit.raw.age]", "column[fruit.ext_view.age]"],
    ]
    assert h.nodes_full == [
        "column[name=age table=ext_view schema=fruit type=INT kind=view subkind=external]",
        "column[name=name table=ext_view schema=fruit type=VARCHAR kind=view subkind=external]",
        "column[name=age table=raw schema=fruit type=INT kind=table]",
        "column[name=name table=raw schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__external_view_protected(holder):
    sql = """
    CREATE EXTERNAL PROTECTED VIEW fruit.ext_view
    AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1
