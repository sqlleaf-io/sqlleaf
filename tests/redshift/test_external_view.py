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
        "column[name=age type=INT properties=[kind=view subkind=external table=ext_view schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=view subkind=external table=ext_view schema=fruit]]",
        "column[name=age type=INT properties=[kind=table table=raw schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
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
