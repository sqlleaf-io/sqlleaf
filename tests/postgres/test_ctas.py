import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import CTASQuery
from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


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


values_exprs = [
    "VALUES (1, 'Alice'), (2, 'Bob');",
    "SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob'));",
    "SELECT * FROM (SELECT * FROM (VALUES (1, 'Alice'), (2, 'Bob')));",
]


@pytest.mark.parametrize("expr", values_exprs)
def test__ctas_with_values(holder, expr):
    sql = f"""
    CREATE TABLE some_table(id, name) AS
    {expr}
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[1]", "column[some_table.id]"],
        ["literal[2]", "column[some_table.id]"],
        ['literal["Alice"]', "column[some_table.name]"],
        ['literal["Bob"]', "column[some_table.name]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


# TODO: support no column names
"""
CREATE TABLE my_new_table AS
VALUES (1, 'Alice'), (2, 'Bob');

-> column1 | column2
"""


def test__ctas_with_execute(holder):
    sql = """
    PREPARE plan AS SELECT name, kind FROM fruit.raw;
    CREATE TABLE fruit.cooked AS EXECUTE plan;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.cooked.name]"],
        ["column[fruit.raw.kind]", "column[fruit.cooked.kind]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2

    # Original
    query: CTASQuery = h.holders[1].original
    assert query.source_info.type == SqlObjectType.PREPARED_STATEMENT
    assert query.target_info.type == SqlObjectType.TABLE

    # Substituted
    query: CTASQuery = h.holders[1].substituted
    # assert query.source_info.type == SqlObjectType.SELECT # TODO: bug - should be recalculated as PREPARED_STATEMENT
    assert query.target_info.type == SqlObjectType.TABLE
    expected_query = "CREATE TABLE fruit.cooked AS SELECT raw.name AS name, raw.kind AS kind FROM fruit.raw AS raw"
    assert query.statement.sql(dialect=DIALECT) == expected_query


def test__ctas_execute_missing_params_fails(holder):
    sql = """
    PREPARE my_plan AS SELECT $1 AS col1;
    CREATE TABLE fruit.cooked AS EXECUTE my_plan;
    """
    with pytest.raises(
        SqlLeafException, match=r"wrong number of parameters for prepared statement \(expected: 1, actual: 0\)"
    ):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_execute_with_params(holder):
    sql = """
    PREPARE my_plan AS SELECT $1 AS col1;
    CREATE TABLE fruit.cooked AS EXECUTE my_plan(5);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["literal[5]", "column[fruit.cooked.col1]"]]
    assert any("literal[name=5" in n for n in h.nodes_full)
    assert any("name=col1" in n and "table=cooked" in n for n in h.nodes_full)


def test__ctas_execute_too_many_params_fails(holder):
    sql = """
    PREPARE my_plan AS SELECT $1 AS col1;
    CREATE TABLE fruit.cooked AS EXECUTE my_plan(5, 6);
    """
    with pytest.raises(
        SqlLeafException, match=r"wrong number of parameters for prepared statement \(expected: 1, actual: 2\)"
    ):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_execute_too_few_params_fails(holder):
    sql = """
    PREPARE my_plan AS SELECT $1 AS col1, $2 AS col2;
    CREATE TABLE fruit.cooked AS EXECUTE my_plan(5);
    """
    with pytest.raises(
        SqlLeafException, match=r"wrong number of parameters for prepared statement \(expected: 2, actual: 1\)"
    ):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_execute_ignoring_extra_params(holder):
    sql = """
    PREPARE my_plan AS SELECT 'Hello' AS col1;
    CREATE TABLE fruit.cooked AS EXECUTE my_plan(5);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['literal["Hello"]', "column[fruit.cooked.col1]"]]
    assert h.nodes_full == [
        'literal[name="Hello" type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
        "column[name=col1 type=VARCHAR properties=[kind=table table=cooked schema=fruit]]",
    ]


def test__ctas_execute_params_without_placeholders(holder):
    sql = """
    PREPARE plan AS SELECT name, kind FROM fruit.raw;
    CREATE TABLE fruit.cooked AS EXECUTE plan(3, 4);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.cooked.name]"],
        ["column[fruit.raw.kind]", "column[fruit.cooked.kind]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
