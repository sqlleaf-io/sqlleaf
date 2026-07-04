import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__select_into(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, age INT);
    CREATE TABLE target (name VARCHAR, age INT);

    SELECT name, age INTO target FROM source;
    SELECT name, age INTO TEMPORARY other FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[other.name]"],
        ["column[source.name]", "column[target.name]"],
        ["column[source.age]", "column[other.age]"],
        ["column[source.age]", "column[target.age]"],
    ]
    assert "column[name=age type=INT properties=[kind=table table=source]]" in h.nodes_full
    assert "column[name=age type=INT properties=[kind=table subkind=temporary table=other]]" in h.nodes_full
    assert len(h.nodes) == 6
    assert len(h.edges) == 4
