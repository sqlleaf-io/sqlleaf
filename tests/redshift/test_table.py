import os
import sys

from sqlleaf.models.query import TableQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__table_temporary(holder):
    sql = """
    CREATE TABLE #banana (name VARCHAR);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert [TableQuery] == h.query_types
    assert h.queries_original[0].property == "temporary"


def test__ctas_distkey_sortkey(holder):
    sql = """
    CREATE TABLE banana
    DISTKEY (name)
    SORTKEY (name, age)
    AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[banana.name]"],
        ["column[fruit.raw.age]", "column[banana.age]"],
    ]
    assert h.nodes_full == [
        "column[name=age table=banana type=INT kind=table]",
        "column[name=name table=banana type=VARCHAR kind=table]",
        "column[name=age table=raw schema=fruit type=INT kind=table]",
        "column[name=name table=raw schema=fruit type=VARCHAR kind=table]",
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__ctas_temporary(holder):
    sql = """
    CREATE TABLE #banana AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[#banana.name]"],
        ["column[fruit.raw.age]", "column[#banana.age]"],
    ]
    assert "column[name=age table=#banana type=INT kind=table subkind=temporary]" in h.nodes_full
    assert "column[name=name table=#banana type=VARCHAR kind=table subkind=temporary]" in h.nodes_full

    assert len(h.nodes) == 4
    assert len(h.edges) == 2
