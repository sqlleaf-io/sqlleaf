import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__datetime_now(holder):
    sql = "INSERT INTO fruit.processed (created_at) SELECT NOW()"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["function[CURRENT_TIMESTAMP]", "column[fruit.processed.created_at]"]]


def test__datetime_current_date(holder):
    sql = "INSERT INTO fruit.processed (inserted_at) SELECT CURRENT_DATE"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["function[CURRENT_DATE]", "column[fruit.processed.inserted_at]"]]


def test__datetime_extract(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT EXTRACT(YEAR FROM created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["var[YEAR]", "function[EXTRACT]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "function[EXTRACT]", "column[fruit.processed.age]"],
    ]


def test__datetime_date_trunc(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT DATE_TRUNC('day', created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[DATE_TRUNC]", "column[fruit.processed.age]"],
        ["var[DAY]", "function[DATE_TRUNC]", "column[fruit.processed.age]"],
    ]


def test__datetime_age(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT AGE(updated_at, created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.updated_at]", "udf[AGE]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "udf[AGE]", "column[fruit.processed.age]"],
    ]


def test__datetime_to_char(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[TO_CHAR]", "column[fruit.processed.name]"],
        ['literal["%Y-%m-%d"]', "function[TO_CHAR]", "column[fruit.processed.name]"],
    ]


def test__datetime_interval_arithmetic(holder):
    # Use different columns to avoid cycles
    sql = "INSERT INTO fruit.processed (updated_at) SELECT created_at + INTERVAL '1 day' FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.processed.created_at]", "function[ADD]", "column[fruit.processed.updated_at]"],
        ['interval["1 DAY"]', "function[ADD]", "column[fruit.processed.updated_at]"],
    ]


def test__datetime_date_part(holder):
    sql = "INSERT INTO fruit.processed (age) SELECT DATE_PART('month', created_at) FROM fruit.processed"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["var[month]", "function[EXTRACT]", "column[fruit.processed.age]"],
        ["column[fruit.processed.created_at]", "function[EXTRACT]", "column[fruit.processed.age]"],
    ]


def test__datetime_make_date(holder):
    sql = "INSERT INTO fruit.processed (inserted_at) SELECT MAKE_DATE(2023, 1, 1)"
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[2023]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"],
        ["literal[1]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"],
        ["literal[1]", "udf[MAKE_DATE]", "column[fruit.processed.inserted_at]"],
    ]


def test__datetime_at_time_zone_literal_timestamp_denver(holder):
    # Result: 2001-02-16 19:38:40-08
    sql = (
        "INSERT INTO fruit.processed (name) "
        "SELECT (TIMESTAMP '2001-02-16 20:38:40' AT TIME ZONE 'America/Denver')::text"
    )
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_at_time_zone_timestamptz_denver(holder):
    # Result: 2001-02-16 18:38:40
    sql = (
        "INSERT INTO fruit.processed (name) "
        "SELECT (TIMESTAMP WITH TIME ZONE '2001-02-16 20:38:40-05' AT TIME ZONE 'America/Denver')::text"
    )
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_at_time_zone_chained_tokyo_chicago(holder):
    # Result: 2001-02-16 05:38:40
    sql = (
        "INSERT INTO fruit.processed (name) "
        "SELECT (TIMESTAMP '2001-02-16 20:38:40' AT TIME ZONE 'Asia/Tokyo' AT TIME ZONE 'America/Chicago')::text"
    )
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_at_local_timestamptz(holder):
    # Result: 2001-02-16 17:38:40
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = (
            "INSERT INTO fruit.processed (name) "
            "SELECT (TIMESTAMP WITH TIME ZONE '2001-02-16 20:38:40-05' AT LOCAL)::text"
        )
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0].startswith("Expecting ). Line 1, Col: 101.")


def test__datetime_at_time_zone_numeric_offset(holder):
    # Result: 2001-02-16 20:38:40
    sql = (
        "INSERT INTO fruit.processed (name) "
        "SELECT (TIMESTAMP WITH TIME ZONE '2001-02-16 20:38:40-05' AT TIME ZONE '+05')::text"
    )
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_time_with_time_zone_at_local(holder):
    # Result: 17:38:40
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = "INSERT INTO fruit.processed (name) SELECT (TIME WITH TIME ZONE '20:38:40-05' AT LOCAL)::text"
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0].startswith("Expecting ). Line 1, Col: 85.")


def test__datetime_transaction_timestamp(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT transaction_timestamp()::text"
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_statement_timestamp(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT statement_timestamp()::text"
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_clock_timestamp(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT clock_timestamp()::text"
    holder(sql=sql, dialect=DIALECT, with_tables=True)


def test__datetime_timeofday(holder):
    sql = "INSERT INTO fruit.processed (name) SELECT timeofday()::text"
    holder(sql=sql, dialect=DIALECT, with_tables=True)
