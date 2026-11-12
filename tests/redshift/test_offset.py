import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "redshift"


def test_offset(holder):
    sql = """
    CREATE TABLE source(id INT, tags SUPER);
    CREATE TABLE target(name VARCHAR, pos INT);

    INSERT INTO target (name, pos)
    SELECT tag, off FROM source s, UNNEST(s.tags) AS tag WITH OFFSET AS off;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes == [
        "counter[]",
        "function[UNNEST]",
        "column[s.tags]",
        "column[tag.off]",
        "column[tag.tag]",
        "column[target.name]",
        "column[target.pos]",
    ]
    assert h.paths == [
        ["column[s.tags]", "function[UNNEST]", "column[tag.tag]", "column[target.name]"],
        ["counter[]", "column[tag.off]", "column[target.pos]"],
    ]
