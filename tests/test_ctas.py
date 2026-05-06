import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

DIALECT = "postgres"

def test__ctas_named_columns(holder):
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


def test__ctas_with_no_data(holder):
    sql = """
    CREATE TABLE fruit.cooked AS
    SELECT name, age FROM fruit.raw
    WITH NO DATA;
    
    INSERT INTO fruit.cooked (name, age)
    SELECT 'apple', 10;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [['literal["apple"]', "column[fruit.cooked.name]"], ["literal[10]", "column[fruit.cooked.age]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__ctas_cte(holder):
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


def test__ctas_values(holder):
    sql = """
    CREATE TABLE some_table(id, name) AS
    VALUES (1, 'Alice'), (2, 'Bob');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[1]', 'column[some_table.id]'],
        ['literal[2]', 'column[some_table.id]'],
        ['literal["Alice"]', 'column[some_table.name]'],
        ['literal["Bob"]', 'column[some_table.name]']
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


# TODO: support no column names
"""
CREATE TABLE my_new_table AS
VALUES (1, 'Alice'), (2, 'Bob');
"""
