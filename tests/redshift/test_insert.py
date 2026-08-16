import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__exclude(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, kind VARCHAR, age INT);
    CREATE TABLE target (name VARCHAR, kind VARCHAR);

    INSERT INTO target
    SELECT * EXCLUDE age FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.name]", "column[target.name]"], ["column[source.kind]", "column[target.kind]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
