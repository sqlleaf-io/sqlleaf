import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__window_qualify(holder):
    sql = """
    INSERT INTO fruit.processed (name)
    SELECT name
    FROM fruit.raw
    QUALIFY row_number() OVER (PARTITION BY age ORDER BY age DESC) <= 2
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.name]", "column[fruit.processed.name]"]]
    assert h.nodes_full == [
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
