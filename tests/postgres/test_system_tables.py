import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


@pytest.mark.skip(reason="todo")
def test__system_tables_postgres(holder):
    sql = """
    INSERT INTO fruit.raw (name)
    SELECT tableowner FROM pg_tables WHERE schemaname = 'public';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    h.generate(sql, dialect="postgres")

    assert h.paths == [
        ["null[NULL]", "column[fruit.b.color]"],
        ["literal[-1]", "column[fruit.b.age]"],
        ["null[NULL]", "column[fruit.a.name]"],
        ["null[NULL]", "column[fruit.a.kind]"],
        ["literal[99]", "column[fruit.a.size]"],
    ]
    assert len(h.nodes) == 10
    assert (
        h.queries[2].statement_transformed.sql() == "INSERT INTO fruit.b (color, age) SELECT NULL AS color, -1 AS age"
    )
