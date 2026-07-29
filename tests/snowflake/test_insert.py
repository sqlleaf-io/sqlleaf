import os
import sys

from sqlleaf.models.query import InsertQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test__multitable_insert_all(holder):
    sql = """
    CREATE TABLE fruit.target1 (c1 INT);
    CREATE TABLE fruit.target2 (c2 INT);
    CREATE TABLE fruit.source (v1 INT, v2 INT);

    INSERT ALL
      INTO fruit.target1 (c1) VALUES (v1)
      INTO fruit.target2 (c2) VALUES (v2)
    SELECT v1, v2 FROM fruit.source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET1.C1]"],
        ["column[FRUIT.SOURCE.V2]", "column[FRUIT.TARGET2.C2]"],
    ]
    downstream_holders = h.holders[3].downstream_holders
    assert [InsertQuery, InsertQuery] == list(map(type, [ch.original for ch in downstream_holders]))
    assert (
        downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET1 (C1) SELECT SOURCE.V1 AS C1 FROM FRUIT.SOURCE AS SOURCE"
    )
    assert (
        downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET2 (C2) SELECT SOURCE.V2 AS C2 FROM FRUIT.SOURCE AS SOURCE"
    )


def test__multitable_insert_first_reversed(holder):
    sql = """
    CREATE TABLE fruit.target1 (c1 INT);
    CREATE TABLE fruit.target2 (c2 INT);
    CREATE TABLE fruit.source (v1 INT, v2 INT);

    INSERT FIRST
      WHEN v1 > 0 THEN
        INTO fruit.target1 (c1) VALUES (v2)
      WHEN v2 > 0 THEN
        INTO fruit.target2 (c2) VALUES (v1)
    SELECT v1, v2 FROM fruit.source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[FRUIT.SOURCE.V2]", "column[FRUIT.TARGET1.C1]"],
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET2.C2]"],
    ]
    downstream_holders = h.holders[3].downstream_holders
    assert [InsertQuery, InsertQuery] == list(map(type, [ch.original for ch in downstream_holders]))
    assert (
        downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET1 (C1) SELECT SOURCE.V2 AS C1 FROM FRUIT.SOURCE AS SOURCE"
    )
    assert (
        downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET2 (C2) SELECT SOURCE.V1 AS C2 FROM FRUIT.SOURCE AS SOURCE"
    )


def test__multitable_insert_all_else(holder):
    sql = """
    CREATE TABLE fruit.target1 (c1 INT);
    CREATE TABLE fruit.target2 (c2 INT);
    CREATE TABLE fruit.target3 (c3 INT);
    CREATE TABLE fruit.source (v1 INT);

    INSERT ALL
      WHEN v1 > 100 THEN
        INTO fruit.target1
      WHEN v1 > 10 THEN
        INTO fruit.target1
        INTO fruit.target2
      ELSE
        INTO fruit.target3
    SELECT v1 FROM fruit.source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET1.C1]"],
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET1.C1]"],
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET2.C2]"],
        ["column[FRUIT.SOURCE.V1]", "column[FRUIT.TARGET3.C3]"],
    ]
    downstream_holders = h.holders[4].downstream_holders
    assert [InsertQuery, InsertQuery, InsertQuery, InsertQuery] == list(
        map(type, [ch.original for ch in downstream_holders])
    )

    assert (
        downstream_holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET1 (C1) SELECT SOURCE.V1 AS C1 FROM FRUIT.SOURCE AS SOURCE"
    )
    assert (
        downstream_holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET1 (C1) SELECT SOURCE.V1 AS C1 FROM FRUIT.SOURCE AS SOURCE"
    )
    assert (
        downstream_holders[2].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET2 (C2) SELECT SOURCE.V1 AS C2 FROM FRUIT.SOURCE AS SOURCE"
    )
    assert (
        downstream_holders[3].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO FRUIT.TARGET3 (C3) SELECT SOURCE.V1 AS C3 FROM FRUIT.SOURCE AS SOURCE"
    )
