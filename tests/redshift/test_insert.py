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


def test__connect_by(holder):
    sql = """
    CREATE TABLE source (id INT, name VARCHAR, kind VARCHAR);
    CREATE TABLE target (id INT, name VARCHAR);

    INSERT INTO target
    SELECT id, name
    FROM source
    WHERE LEVEL < 4
    START WITH name = 'John'
    CONNECT BY PRIOR id = 1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.id]", "column[target.id]"],
        ["column[source.name]", "column[target.name]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
