import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"

COMMON_SQL = """
CREATE TYPE my_type AS (a INT, b TEXT, c FLOAT);
CREATE TABLE t1 (a INT, b TEXT, c FLOAT);
CREATE TABLE dest (a INT, b TEXT, c FLOAT);
"""


# TODO: bug - first inner column is dropped
def test__row_default_aliases(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest (b, c)
    SELECT f2, f3 FROM (SELECT (ROW('Alice'::text, 25, 10.0)).*) t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (b, c) SELECT t.f2 AS b, t.f3 AS c FROM (SELECT 25 AS f2, 10.0 AS f3) AS t"
    )
    assert h.paths == [
        ["literal[25]", "column[t.f2]", "column[dest.b]"],
        ["literal[10.0]", "column[t.f3]", "column[dest.c]"],
    ]


def test__row_default_aliases_star(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest (a, b, c)
    SELECT * FROM (SELECT (ROW(5, 25, 10.0)).*) t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a, b, c) SELECT t.f1 AS a, t.f2 AS b, t.f3 AS c FROM (SELECT 5 AS f1, 25 AS f2, 10.0 AS f3) AS t"
    )
    assert h.paths == [
        ["literal[5]", "column[t.f1]", "column[dest.a]"],
        ["literal[25]", "column[t.f2]", "column[dest.b]"],
        ["literal[10.0]", "column[t.f3]", "column[dest.c]"],
    ]


def test__row_composite_column(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest2 (val my_type);
    INSERT INTO dest2 SELECT ROW(a, b, c)::my_type FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest2 (val) SELECT CAST(ROW(t1.a, t1.b, t1.c) AS my_type) AS val FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
    ]


def test__row_literal_values(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest2 (val my_type);
    INSERT INTO dest2 VALUES (ROW(1, 'x', 2.0)::my_type), (ROW(3, 'y', 4.0)::my_type);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest2 (val) SELECT CAST(ROW(1, 'x', 2.0) AS my_type) AS val UNION ALL SELECT CAST(ROW(3, 'y', 4.0) AS my_type) AS val"
    )
    assert h.paths == [
        ["literal[1]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ['literal["x"]', "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["literal[2.0]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["literal[3]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ['literal["y"]', "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["literal[4.0]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
    ]


def test__row_udf_argument(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT get_a(ROW(a, b, c)::my_type) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a) SELECT GET_A(CAST(ROW(t1.a, t1.b, t1.c) AS my_type)) AS a FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "udf[ROW]", "function[CAST]", "udf[GET_A]", "column[dest.a]"],
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "udf[GET_A]", "column[dest.a]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "udf[GET_A]", "column[dest.a]"],
    ]


def test__row_array_agg(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest3 (val my_type[]);
    INSERT INTO dest3 SELECT array_agg(ROW(a, b, c)::my_type) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest3 (val) SELECT ARRAY_AGG(CAST(ROW(t1.a, t1.b, t1.c) AS my_type)) AS val FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "udf[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[dest3.val]"],
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[dest3.val]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[dest3.val]"],
    ]


def test__row_jsonb(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest4 (val JSONB);
    INSERT INTO dest4 SELECT jsonb_build_object('data', ROW(a, b, c)::my_type) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest4 (val) SELECT JSONB_BUILD_OBJECT('data', CAST(ROW(t1.a, t1.b, t1.c) AS my_type)) AS val FROM t1 AS t1"
    )
    assert h.paths == [
        ['literal["data"]', "udf[JSONB_BUILD_OBJECT]", "column[dest4.val]"],
        ["column[t1.a]", "udf[ROW]", "function[CAST]", "udf[JSONB_BUILD_OBJECT]", "column[dest4.val]"],
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "udf[JSONB_BUILD_OBJECT]", "column[dest4.val]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "udf[JSONB_BUILD_OBJECT]", "column[dest4.val]"],
    ]


def test__row_nested_row(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TYPE outer_type AS (inner_val my_type, label TEXT);
    CREATE TABLE dest5 (val outer_type);
    INSERT INTO dest5 SELECT ROW(ROW(a, b, c)::my_type, chr(39))::outer_type FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[5].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest5 (val) SELECT CAST(ROW(CAST(ROW(t1.a, t1.b, t1.c) AS my_type), CHR(39)) AS outer_type) AS val FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "udf[ROW]", "function[CAST]", "udf[ROW]", "function[CAST]", "column[dest5.val]"],
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "udf[ROW]", "function[CAST]", "column[dest5.val]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "udf[ROW]", "function[CAST]", "column[dest5.val]"],
        ["literal[39]", "function[CHR]", "udf[ROW]", "function[CAST]", "column[dest5.val]"],
    ]


# TODO: bug in the aliasing
def test__row_scalar_subquery(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest2 (val my_type);
    INSERT INTO dest2 SELECT ROW((SELECT max(a) FROM t1), b, c)::my_type FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest2 (val) SELECT CAST(ROW(_u_0._col_0, t1.b, t1.c) AS my_type) AS val FROM t1 AS t1 CROSS JOIN (SELECT MAX(t1.a) AS _col_0 FROM t1 AS t1) AS _u_0"
    )
    assert h.paths == [
        ["column[t1.b]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["column[t1.c]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
        ["column[t1.a]", "function[MAX]", "column[_u_0._col_0]", "udf[ROW]", "function[CAST]", "column[dest2.val]"],
    ]


def test__row_access_single_field(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).a FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a) SELECT t1.a AS a FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "column[dest.a]"],
    ]


def test__row_access_multiple_fields(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).a, (ROW(a, b, c)::my_type).b FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a, b) SELECT t1.a AS a, t1.b AS b FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "column[dest.a]"],
        ["column[t1.b]", "column[dest.b]"],
    ]


def test__row_access_wildcard_expansion(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).* FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a, b, c) SELECT t1.a AS a, t1.b AS b, t1.c AS c FROM t1 AS t1"
    )
    assert h.paths == [
        ["column[t1.a]", "column[dest.a]"],
        ["column[t1.b]", "column[dest.b]"],
        ["column[t1.c]", "column[dest.c]"],
    ]


def test__row_access_case_when(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest
    SELECT (CASE WHEN a > 2
                 THEN ROW(a, b, c)::my_type
                 ELSE ROW(0, 'default', 0.0)::my_type
            END).a
    FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a) SELECT CASE WHEN t1.a > 2 THEN t1.a ELSE 0 END AS a FROM t1 AS t1"
    )
    assert h.paths == [
        ["literal[0]", "column[dest.a]"],
        ["column[t1.a]", "column[dest.a]"],
    ]


def test__row_access_cte(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest
    WITH cte AS (SELECT ROW(a, b, c)::my_type AS r FROM t1)
    SELECT (r).a, (r).b, (r).c FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a, b, c) WITH cte AS (SELECT t1.a AS a, t1.b AS b, t1.c AS c FROM t1 AS t1) SELECT cte.a AS a, cte.b AS b, cte.c AS c FROM cte AS cte"
    )
    assert h.paths == [
        ["column[t1.a]", "column[cte.a]", "column[dest.a]"],
        ["column[t1.b]", "column[cte.b]", "column[dest.b]"],
        ["column[t1.c]", "column[cte.c]", "column[dest.c]"],
    ]


def test__row_access_lateral(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest
    SELECT (r).a, (r).b, (r).c
    FROM t1, LATERAL (SELECT ROW(a, b, c)::my_type AS r) AS sub;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO dest (a, b, c) SELECT sub.a AS a, sub.b AS b, sub.c AS c FROM t1 AS t1 CROSS JOIN LATERAL (SELECT t1.a AS a, t1.b AS b, t1.c AS c) AS sub"
    )
    assert h.paths == [
        ["column[t1.a]", "column[sub.a]", "column[dest.a]"],
        ["column[t1.b]", "column[sub.b]", "column[dest.b]"],
        ["column[t1.c]", "column[sub.c]", "column[dest.c]"],
    ]


# def test__row_unnest_array(holder):
#     sql = f"""
#     {COMMON_SQL}
#     INSERT INTO dest
#     SELECT (u).a, (u).b, (u).c
#     FROM unnest(ARRAY(SELECT ROW(a, b, c)::my_type FROM t1)) AS u;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#
#     assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
#         "INSERT INTO dest (a, b, c) SELECT u.a AS a, u.b AS b, u.c AS c FROM UNNEST(ARRAY(SELECT CAST(ROW(t1.a, t1.b, t1.c) AS my_type) AS ROW FROM t1 AS t1)) AS u"
#     )
#     # TODO: fix this
#     assert h.paths == []
#     # assert h.paths == [
#     #     "column[t1.a]", "function[unnest]", "column[u.a]", "function[dest.a]",
#     #     "column[t1.b]", "function[unnest]", "column[u.b]", "function[dest.b]",
#     #     "column[t1.c]", "function[unnest]", "column[u.c]", "function[dest.c]"
#     # ]


def test__row_update_set_row(holder):
    sql = f"""
    {COMMON_SQL}
    UPDATE t1 SET (a, b) = ROW(a * 10, b || '!');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql() == (
        "INSERT INTO t1 (a, b) SELECT t1.a * 10 AS a, t1.b || '!' AS b FROM t1 AS t1"
    )
    assert h.paths == [
        ["literal[10]", "function[MUL]", "column[t1.a]", "function[MUL]"],
        ['literal["!"]', "function[DPIPE]", "column[t1.b]", "function[DPIPE]"],
        ["column[t1.a]", "function[MUL]", "column[t1.a]"],
        ["column[t1.b]", "function[DPIPE]", "column[t1.b]"],
    ]
