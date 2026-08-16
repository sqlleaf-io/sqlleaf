import pytest

from tests.new_fixtures import holder as holder


DIALECT = ""


def test__ctas_with_named_columns(holder):
    sql = """
    CREATE TABLE fruit.cooked (col1, col2) AS
    SELECT name, kind FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.cooked.col1]"],
        ["column[fruit.raw.kind]", "column[fruit.cooked.col2]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__ctas_with_cte(holder):
    sql = """
    CREATE TABLE fruit.cte AS
    WITH data(col1, col2) AS (
        SELECT name, kind FROM fruit.raw
    )
    SELECT * FROM data;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[data.col1]", "column[fruit.cte.col1]"],
        ["column[fruit.raw.kind]", "column[data.col2]", "column[fruit.cte.col2]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4
