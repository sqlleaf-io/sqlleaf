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
        "INSERT INTO public.dest (b, c) SELECT t.f2 AS b, t.f3 AS c FROM (SELECT 25 AS f2, 10.0 AS f3) AS t"
    )
    assert h.paths == [
        ["literal[25]", "column[t.f2]", "column[public.dest.b]"],
        ["literal[10.0]", "column[t.f3]", "column[public.dest.c]"],
    ]


def test__row_default_aliases_star(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest (a, b, c)
    SELECT * FROM (SELECT (ROW(5, 25, 10.0)).*) t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest (a, b, c) SELECT t.f1 AS a, t.f2 AS b, t.f3 AS c FROM (SELECT 5 AS f1, 25 AS f2, 10.0 AS f3) AS t"
    )
    assert h.paths == [
        ["literal[5]", "column[t.f1]", "column[public.dest.a]"],
        ["literal[25]", "column[t.f2]", "column[public.dest.b]"],
        ["literal[10.0]", "column[t.f3]", "column[public.dest.c]"],
    ]


def test__row_composite_column(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest2 (val my_type);
    INSERT INTO dest2 SELECT ROW(a, b, c)::my_type FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest2 (val) SELECT CAST(ROW(t1.a, t1.b, t1.c) AS my_type) AS val FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["column[public.t1.b]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["column[public.t1.c]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
    ]


def test__row_literal_values(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest2 (val my_type);
    INSERT INTO dest2 VALUES (ROW(1, 'x', 2.0)::my_type), (ROW(3, 'y', 4.0)::my_type);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest2 (val) SELECT CAST(ROW(1, 'x', 2.0) AS my_type) AS val UNION ALL SELECT CAST(ROW(3, 'y', 4.0) AS my_type) AS val"
    )
    assert h.paths == [
        ["literal[1]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ['literal["x"]', "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["literal[2.0]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["literal[3]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ['literal["y"]', "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["literal[4.0]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
    ]


def test__row_udf_argument(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).a FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest (a) SELECT t1.a AS a FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "column[public.dest.a]"],
    ]


def test__row_array_agg(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest3 (val my_type[]);
    INSERT INTO dest3 SELECT array_agg(ROW(a, b, c)::my_type) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest3 (val) SELECT ARRAY_AGG(CAST(ROW(t1.a, t1.b, t1.c) AS my_type)) AS val FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "function[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[public.dest3.val]"],
        ["column[public.t1.b]", "function[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[public.dest3.val]"],
        ["column[public.t1.c]", "function[ROW]", "function[CAST]", "function[ARRAY_AGG]", "column[public.dest3.val]"],
    ]


def test__row_jsonb(holder):
    sql = f"""
    {COMMON_SQL}
    CREATE TABLE dest4 (val JSONB);
    INSERT INTO dest4 SELECT jsonb_build_object('data', ROW(a, b, c)::my_type) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[4].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest4 (val) SELECT JSONB_BUILD_OBJECT('data', CAST(ROW(t1.a, t1.b, t1.c) AS my_type)) AS val FROM public.t1 AS t1"
    )
    assert h.paths == [
        ['literal["data"]', "function[JSONB_BUILD_OBJECT]", "column[public.dest4.val]"],
        [
            "column[public.t1.a]",
            "function[ROW]",
            "function[CAST]",
            "function[JSONB_BUILD_OBJECT]",
            "column[public.dest4.val]",
        ],
        [
            "column[public.t1.b]",
            "function[ROW]",
            "function[CAST]",
            "function[JSONB_BUILD_OBJECT]",
            "column[public.dest4.val]",
        ],
        [
            "column[public.t1.c]",
            "function[ROW]",
            "function[CAST]",
            "function[JSONB_BUILD_OBJECT]",
            "column[public.dest4.val]",
        ],
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
        "INSERT INTO public.dest5 (val) SELECT CAST(ROW(CAST(ROW(t1.a, t1.b, t1.c) AS my_type), CHR(39)) AS outer_type) AS val FROM public.t1 AS t1"
    )
    assert h.paths == [
        [
            "column[public.t1.a]",
            "function[ROW]",
            "function[CAST]",
            "function[ROW]",
            "function[CAST]",
            "column[public.dest5.val]",
        ],
        [
            "column[public.t1.b]",
            "function[ROW]",
            "function[CAST]",
            "function[ROW]",
            "function[CAST]",
            "column[public.dest5.val]",
        ],
        [
            "column[public.t1.c]",
            "function[ROW]",
            "function[CAST]",
            "function[ROW]",
            "function[CAST]",
            "column[public.dest5.val]",
        ],
        ["literal[39]", "function[CHR]", "function[ROW]", "function[CAST]", "column[public.dest5.val]"],
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
        "INSERT INTO public.dest2 (val) SELECT CAST(ROW((SELECT MAX(t1.a) AS _col_0 FROM public.t1 AS t1), t1.b, t1.c) AS my_type) AS val FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "function[MAX]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["column[public.t1.b]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
        ["column[public.t1.c]", "function[ROW]", "function[CAST]", "column[public.dest2.val]"],
    ]


def test__row_access_single_field(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).a FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest (a) SELECT t1.a AS a FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "column[public.dest.a]"],
    ]


def test__row_access_multiple_fields(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).a, (ROW(a, b, c)::my_type).b FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest (a, b) SELECT t1.a AS a, t1.b AS b FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "column[public.dest.a]"],
        ["column[public.t1.b]", "column[public.dest.b]"],
    ]


def test__row_access_wildcard_expansion(holder):
    sql = f"""
    {COMMON_SQL}
    INSERT INTO dest SELECT (ROW(a, b, c)::my_type).* FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[3].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO public.dest (a, b, c) SELECT t1.a AS a, t1.b AS b, t1.c AS c FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["column[public.t1.a]", "column[public.dest.a]"],
        ["column[public.t1.b]", "column[public.dest.b]"],
        ["column[public.t1.c]", "column[public.dest.c]"],
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
        "INSERT INTO public.dest (a) SELECT CASE WHEN t1.a > 2 THEN t1.a ELSE 0 END AS a FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["literal[0]", "column[public.dest.a]"],
        ["column[public.t1.a]", "column[public.dest.a]"],
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
        "INSERT INTO public.dest (a, b, c) WITH cte AS (SELECT t1.a AS a, t1.b AS b, t1.c AS c FROM public.t1 AS t1) SELECT cte.a AS a, cte.b AS b, cte.c AS c FROM cte AS cte"
    )
    assert h.paths == [
        ["column[public.t1.a]", "column[cte.a]", "column[public.dest.a]"],
        ["column[public.t1.b]", "column[cte.b]", "column[public.dest.b]"],
        ["column[public.t1.c]", "column[cte.c]", "column[public.dest.c]"],
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
        "INSERT INTO public.dest (a, b, c) SELECT sub.a AS a, sub.b AS b, sub.c AS c FROM public.t1 AS t1 CROSS JOIN LATERAL (SELECT t1.a AS a, t1.b AS b, t1.c AS c) AS sub"
    )
    assert h.paths == [
        ["column[t1.a]", "column[sub.a]", "column[public.dest.a]"],
        ["column[t1.b]", "column[sub.b]", "column[public.dest.b]"],
        ["column[t1.c]", "column[sub.c]", "column[public.dest.c]"],
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
        "INSERT INTO public.t1 (a, b) SELECT t1.a * 10 AS a, t1.b || '!' AS b FROM public.t1 AS t1"
    )
    assert h.paths == [
        ["literal[10]", "function[MUL]", "column[public.t1.a]", "function[MUL]"],
        ['literal["!"]', "function[DPIPE]", "column[public.t1.b]", "function[DPIPE]"],
        ["column[public.t1.a]", "function[MUL]", "column[public.t1.a]"],
        ["column[public.t1.b]", "function[DPIPE]", "column[public.t1.b]"],
    ]
