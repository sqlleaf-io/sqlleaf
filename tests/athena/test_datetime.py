import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__select_for_timestamp_as_of_drops_clause(holder):
    sql = """
    CREATE TABLE source (id INT, name VARCHAR);
    CREATE TABLE target (id INT, name VARCHAR);
    INSERT INTO target (id, name)
    SELECT * FROM source FOR TIMESTAMP AS OF (current_timestamp - interval '1' day);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.default.source.id]", "column[awsdatacatalog.default.target.id]"],
        ["column[awsdatacatalog.default.source.name]", "column[awsdatacatalog.default.target.name]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_for_version_as_of_drops_clause(holder):
    sql = """
    CREATE TABLE source (id INT, name VARCHAR);
    CREATE TABLE target (id INT, name VARCHAR);
    INSERT INTO target (id, name)
    SELECT * FROM source FOR VERSION AS OF 949530903748831860;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.default.source.id]", "column[awsdatacatalog.default.target.id]"],
        ["column[awsdatacatalog.default.source.name]", "column[awsdatacatalog.default.target.name]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
