import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__view(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);

    CREATE VIEW my_view AS SELECT name, amount FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[my_view.name]"],
        ["column[source.amount]", "column[my_view.amount]"],
    ]
    assert h.nodes_full == [
        "column[name=amount table=my_view type=INT kind=view]",
        "column[name=name table=my_view type=VARCHAR kind=view]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=name table=source type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


# Not supported:
# - CREATE EXTERNAL PROTECTED VIEW
# Parser error:
# - CREATE EXTERNAL VIEW IF NOT EXISTS AS
def test__view_external(holder):
    sql = """
    CREATE EXTERNAL VIEW fruit.ext_view
    AS SELECT name, age FROM fruit.raw;
    """

    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.ext_view.name]"],
        ["column[fruit.raw.age]", "column[fruit.ext_view.age]"],
    ]
    assert "column[name=name table=ext_view schema=fruit type=VARCHAR kind=view subkind=external]" in h.nodes_full
    assert "column[name=age table=ext_view schema=fruit type=INT kind=view subkind=external]" in h.nodes_full

    assert len(h.nodes) == 4
    assert len(h.edges) == 2
