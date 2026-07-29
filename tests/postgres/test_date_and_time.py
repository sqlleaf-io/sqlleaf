import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test_now(holder):
    sql = "INSERT INTO fruit.processed (created_at) SELECT NOW()"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"]
    ]


def test_current_date(holder):
    sql = "INSERT INTO fruit.processed (inserted_at) SELECT CURRENT_DATE"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["function[CURRENT_DATE]", "column[fruit.processed.inserted_at]"]
    ]


def test_extract(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT EXTRACT(YEAR FROM created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["var[YEAR]", "function[EXTRACT]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "function[EXTRACT]", "column[fruit.processed.age]"]
    ]


def test_date_trunc(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT DATE_TRUNC('day', created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[DATE_TRUNC]", "column[fruit.processed.age]"],
        ["var[DAY]", "function[DATE_TRUNC]", "column[fruit.processed.age]"]
    ]


def test_age(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT AGE(updated_at, created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.updated_at]", "udf[AGE]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "udf[AGE]", "column[fruit.processed.age]"]
    ]


def test_to_char(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[TO_CHAR]", "column[fruit.processed.name]"],
        ["literal[\"%Y-%m-%d\"]", "function[TO_CHAR]", "column[fruit.processed.name]"]
    ]


def test_interval_arithmetic(holder):
    # Use different columns to avoid cycles
    sql = "INSERT INTO fruit.processed (updated_at) SELECT created_at + INTERVAL '1 day' FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[ADD]", "column[fruit.processed.updated_at]"],
        ["interval[\"1 DAY\"]", "function[ADD]", "column[fruit.processed.updated_at]"]
    ]


def test_date_part(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT DATE_PART('month', created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["var[month]", "function[EXTRACT]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "function[EXTRACT]", "column[fruit.processed.age]"]
    ]


def test_make_date(holder):
    sql = "INSERT INTO fruit.processed (inserted_at) SELECT MAKE_DATE(2023, 1, 1)"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[2023]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"],
        ["literal[1]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"],
        ["literal[1]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"]
    ]
