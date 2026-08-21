import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import InsertQuery

DIALECT = ""


def test__insert_select_with_aliases(holder):
    sql = "INSERT INTO fruit.raw SELECT 'yellow' as name, UPPER('banana') AS kind;"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__insert_select_without_aliases(holder):
    sql = "INSERT INTO fruit.raw SELECT 'yellow', UPPER('banana');"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["yellow"]', "column[fruit.raw.name]"],
        ['literal["banana"]', "function[UPPER]", "column[fruit.raw.kind]"],
    ]
    assert [InsertQuery] == h.query_types


def test__insert_select_star_with_continue_on_error(holder):
    sql = """
    INSERT INTO fruit.raw SELECT * FROM t2;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True, on_error="continue")

    assert h.paths == [
        ["star[*]", "column[fruit.raw.name]"],
    ]
    assert [InsertQuery] == h.query_types
