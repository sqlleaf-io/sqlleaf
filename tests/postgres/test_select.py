import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import InsertQuery, TableQuery
from tests.new_fixtures import holder as holder
from tests.new_fixtures import to_sql

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import sqlglot

DIALECT = "postgres"

# TODO:
#  postgres=# create table f as select 'a';
# SELECT 1
# postgres=# table f;
#  ?column?
# ----------
#  a
#
# -- Must be accessed using double quotes
# select "?column?" from f;
#  ?column?
# ----------
#  a


literal_ones = [
    "(1)",
    "((1))",
    "(((1)))",
]


@pytest.mark.parametrize("case", literal_ones)
def test__select_parens(holder, case):
    sql = f"""
    CREATE TABLE person (age INT);

    INSERT INTO person (age)
    SELECT ({case})
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=person]]",
    ]
    assert h.paths == [["literal[1]", "column[person.age]"]]
    assert len(h.edges) == 1


def test__select_values(holder):
    sql = """
    INSERT INTO fruit.processed (name, kind)
    SELECT DISTINCT ON (num) * FROM (VALUES (1, 'one'), (2, 'two')) AS t (num, letter);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed (name, kind) SELECT DISTINCT ON (t.num) t.num AS name, t.letter AS kind FROM (SELECT 1 AS num, 'one' AS letter UNION ALL SELECT 2 AS num, 'two' AS letter) AS t"
    )

    assert h.paths == [
        ["literal[1]", "column[t.num]", "column[fruit.processed.name]"],
        ["literal[2]", "column[t.num]", "column[fruit.processed.name]"],
        ['literal["one"]', "column[t.letter]", "column[fruit.processed.kind]"],
        ['literal["two"]', "column[t.letter]", "column[fruit.processed.kind]"],
    ]
    assert "column[name=letter type=VARCHAR properties=[kind=derived_table table=t statement=0]]" in h.nodes_full
    assert len(h.nodes) == 8
    assert len(h.edges) == 6


def test__select_basic(holder):
    sql = """
    CREATE TABLE source(name VARCHAR);

    SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.holders[1].transformed.statement.sql(dialect=DIALECT) == "SELECT source.name AS name FROM source AS source"
    assert h.paths == []
    assert h.nodes_full == []


def test__select_unknown_target_table_fails(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        INSERT INTO unknown_table (name) SELECT 1;
        """
        holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0] == "Could not find 'unknown_table' of type 'table' in mapping."


def test__select_unknown_source_table_fails(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        INSERT INTO fruit.processed (name) SELECT name FROM some_unknown;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0] == "Unknown table: some_unknown"


def test__select_dpipe_cte(holder):
    sql = """
    WITH cte AS (
        SELECT 'hello' AS other
    )
    INSERT INTO fruit.processed (kind)
    SELECT
        c.other || c.other as kind
    FROM cte AS c
    ;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.nodes_full == [
        'literal[name="hello" type=VARCHAR position=[query_depth=1 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]',
        "function[name=DPIPE type=VARCHAR position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=other type=VARCHAR properties=[kind=cte table=cte statement=0]]",
        "column[name=kind type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
    ]
    assert h.paths == [
        ['literal["hello"]', "column[cte.other]", "function[DPIPE]", "column[fruit.processed.kind]"],
        ['literal["hello"]', "column[cte.other]", "function[DPIPE]", "column[fruit.processed.kind]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 4


def test__select_subquery(holder):
    sql = """
    INSERT INTO fruit.processed (age) SELECT (SELECT (SELECT r.age * 2 AS age) AS age1) AS age FROM fruit.raw AS r;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    insert_query = h.holders[0]
    insert_after = [
        "INSERT INTO fruit.processed (age) SELECT (SELECT (SELECT r.age * 2 AS age) AS age1) AS age FROM fruit.raw AS r"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert h.paths == [
        ["column[fruit.raw.age]", "function[MUL]", "column[fruit.processed.age]"],
        ["literal[2]", "function[MUL]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3


def test__select_dpipe(holder):
    sql = """
    INSERT INTO fruit.processed (kind)
    SELECT
        name || r.name || upper(r.name) as kind
    FROM fruit.raw AS r
    ;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    # a || b || c  ->  (a || b) || c
    #                     ^     ^
    #                  DPIPE1  DPIPE2
    #
    # expect: a -> dpipe1 -> dpipe2
    # expect: b -> dpipe1 -> dpipe2
    # expect: c -> dpipe2

    assert h.paths == [
        ["column[fruit.raw.name]", "function[DPIPE]", "function[DPIPE]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.name]", "function[DPIPE]", "function[DPIPE]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.name]", "function[UPPER]", "function[DPIPE]", "column[fruit.processed.kind]"],
    ]
    assert len(h.nodes) == 5
    assert len(h.edges) == 6


def test__select_case(holder):
    sql = """
    INSERT INTO fruit.processed (age, number)
    SELECT
        CASE WHEN name = 'John' THEN 1 ELSE 2 END AS age,
        CASE WHEN name = 'John' THEN
            CASE WHEN age > 10 THEN 5 END
        ELSE 6 END AS number
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[2]", "column[fruit.processed.age]"],
        ["literal[1]", "column[fruit.processed.age]"],
        ["literal[6]", "column[fruit.processed.number]"],
        ["null[NULL]", "column[fruit.processed.number]"],
        ["literal[5]", "column[fruit.processed.number]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__select_cast(holder):
    sql = """
    INSERT INTO fruit.processed (age)
    SELECT name::int AS age
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["column[fruit.raw.name]", "function[CAST]", "column[fruit.processed.age]"]]
    assert h.nodes_full == [
        "function[name=CAST type=INT position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
    assert len(h.edges) == 2


def test__select_filter_and_where(holder):
    sql = """
    INSERT INTO fruit.processed (age, amount)
    SELECT
        SUM(age) FILTER (WHERE name = 'John') AS age,
        COUNT(*) FILTER (WHERE CURRENT_USER = 'john') AS amount
    FROM fruit.raw;

    INSERT INTO fruit.processed (age)
    SELECT 1 AS age
    WHERE CURRENT_USER = 'john';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.age]", "function[SUM]", "column[fruit.processed.age]"],
        ["star[*]", "function[COUNT]", "column[fruit.processed.amount]"],
        ["literal[1]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5
    assert (
        h.holders[0].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO fruit.processed (age, amount) SELECT SUM(raw.age) AS age, COUNT(*) AS amount FROM fruit.raw AS raw"  # noqa: E501
    )
    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (age) SELECT 1 AS age"  # noqa: E501
    )


def test__select_hidden_system_columns(holder):
    sql = """
    CREATE TABLE fruit.new AS SELECT 'hello' AS name;

    -- Ensure CTAS works
    INSERT INTO fruit.processed (name)
    SELECT xmax
    FROM fruit.new;

    -- Ensure aliases work
    INSERT INTO fruit.processed (age, amount, number)
    SELECT age, r.xmax, xmax
    FROM fruit.raw AS r;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["hello"]', "column[fruit.new.name]"],
        ["column[fruit.new.xmax]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
        ["column[fruit.raw.xmax]", "column[fruit.processed.amount]"],
        ["column[fruit.raw.xmax]", "column[fruit.processed.number]"],
    ]
    assert "column[name=xmax type=OID properties=[kind=table table=new schema=fruit]]" in h.nodes_full
    assert len(h.nodes) == 9
    assert len(h.edges) == 5


def test__select_fails_unknown_column(holder):
    with pytest.raises(sqlglot.errors.OptimizeError) as e:
        sql = """
        INSERT INTO fruit.processed (name)
        SELECT hello
        FROM fruit.raw;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0].startswith("Column 'hello' could not be resolved.")


tests = [
    ("-10", "literal"),
    ("10", "literal"),
    ("TRUE", "literal"),
    ("NULL", "null"),
    ("LOCALTIME()", "function"),
]


@pytest.mark.parametrize("case", tests)
def test__select_value_twice(holder, case):
    value, kind = case
    sql = f"""
    INSERT INTO fruit.processed (name, age)
    SELECT {value} as name, {value} as age;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    name = value.removesuffix("()")
    assert h.paths == [
        [f"{kind}[{name}]", "column[fruit.processed.name]"],
        [f"{kind}[{name}]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_window_function(holder):
    sql = """
    INSERT INTO fruit.processed (amount, age)
    SELECT
        ROW_NUMBER() OVER (ORDER BY name DESC) AS amount,
        RANK() OVER (PARTITION BY age ORDER BY kind) AS age
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.paths == [
        ["window[RANK]", "column[fruit.processed.age]"],
        ["window[ROW_NUMBER]", "column[fruit.processed.amount]"],
    ]
    assert h.nodes_full == [
        "window[name=RANK type=BIGINT]",
        "window[name=ROW_NUMBER type=BIGINT]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=amount type=INT properties=[kind=table table=processed schema=fruit]]",
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_join_to_self(holder):
    sql = """
    INSERT INTO fruit.processed (name, age, kind)
    SELECT
        p.name,
        r.age as age,
        color
    FROM fruit.raw r
    INNER JOIN fruit.processed p ON r.name = p.name;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.paths == [
        ["column[fruit.raw.color]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
        ["column[fruit.processed.name]", "column[fruit.processed.name]"],
    ]
    assert len(h.nodes) == 5
    assert len(h.edges) == 3


def test__select_assorted(holder):
    sql = """
    CREATE TABLE anything(name1 VARCHAR, name2 VARCHAR);

    INSERT INTO anything
    SELECT
        ARRAY[1,2,3] as name1,
        INTERVAL '-10.75 MINUTE' as name2;

    INSERT INTO anything SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        "literal[name={1,2,3} type=ARRAY<INT> position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]"
        in h.nodes_full
    )
    assert (
        'interval[name="-10.75 MINUTE" type=INTERVAL position=[query_depth=0 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]'  # noqa: E501
        in h.nodes_full
    )
    assert len(h.nodes) == 5
    assert len(h.edges) == 3


def test__select_rows_from(holder):
    sql = """
    INSERT INTO fruit.processed (name, age, kind, amount)
    SELECT *
    FROM ROWS FROM
        (
            unnest(ARRAY['x', 'y']),
            json_to_recordset('[{"a":40,"b":"foo"}]') AS (a INTEGER, b TEXT),
            generate_series(1, 3)
        ) AS x (name, age, kind, amount)
    ORDER BY age;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.nodes_full == [
        'literal[name="[{"a":40,"b":"foo"}]" type=VARCHAR position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=1 func_arg=0]]',
        "literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=0 select=3 func_depth=1 func_arg=0]]",
        "literal[name=3 type=INT position=[query_depth=0 query_width=0 statement=0 select=3 func_depth=1 func_arg=1]]",
        "function[name=GENERATE_SERIES type=UNKNOWN position=[query_depth=0 query_width=0 statement=0 select=3 func_depth=0 func_arg=0]]",
        "function[name=UNNEST type=VARCHAR position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=a type=INT properties=[kind=derived_table statement=0]]",
        "column[name=b type=TEXT properties=[kind=derived_table statement=0]]",
        "function[name=JSON_TO_RECORDSET type=UNKNOWN position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "literal[name={'x','y'} type=ARRAY<VARCHAR> position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=1 func_arg=0]]",
        "column[name=age type=UNKNOWN properties=[kind=derived_table table=x statement=0]]",
        "column[name=amount type=UNKNOWN properties=[kind=derived_table table=x statement=0]]",
        "column[name=kind type=UNKNOWN properties=[kind=derived_table table=x statement=0]]",
        "column[name=name type=UNKNOWN properties=[kind=derived_table table=x statement=0]]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=amount type=INT properties=[kind=table table=processed schema=fruit]]",
        "column[name=kind type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
    ]
    # TODO: bug in duplicate paths for JSON_TO_RECORDSET?
    assert h.paths == [
        ["literal[{'x','y'}]", "function[UNNEST]", "column[x.name]", "column[fruit.processed.name]"],
        [
            'literal["[{"a":40,"b":"foo"}]"]',
            "function[JSON_TO_RECORDSET]",
            "column[a]",
            "column[x.age]",
            "column[fruit.processed.age]",
        ],
        [
            'literal["[{"a":40,"b":"foo"}]"]',
            "function[JSON_TO_RECORDSET]",
            "column[b]",
            "column[x.kind]",
            "column[fruit.processed.kind]",
        ],
        [
            'literal["[{"a":40,"b":"foo"}]"]',
            "function[JSON_TO_RECORDSET]",
            "column[a]",
            "column[x.age]",
            "column[fruit.processed.age]",
        ],
        [
            'literal["[{"a":40,"b":"foo"}]"]',
            "function[JSON_TO_RECORDSET]",
            "column[b]",
            "column[x.kind]",
            "column[fruit.processed.kind]",
        ],
        ["literal[1]", "function[GENERATE_SERIES]", "column[x.amount]", "column[fruit.processed.amount]"],
        ["literal[3]", "function[GENERATE_SERIES]", "column[x.amount]", "column[fruit.processed.amount]"],
    ]
    assert len(h.nodes) == 17
    assert len(h.edges) == 15


def test__select_lateral(holder):
    sql = """
    CREATE TABLE fruit.new (name VARCHAR, age INT);
    INSERT INTO fruit.new (name, age)
    SELECT
        lat.name,
        r.age as age
    FROM fruit.raw r,
    LATERAL (SELECT name FROM fruit.processed p WHERE p.name = r.name LIMIT 1) lat;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.paths == [
        ["column[fruit.processed.name]", "column[lat.name]", "column[fruit.new.name]"],
        ["column[fruit.raw.age]", "column[fruit.new.age]"],
    ]
    assert h.nodes_full == [
        "column[name=name type=UNKNOWN properties=[kind=udtf table=lat]]",
        "column[name=age type=INT properties=[kind=table table=new schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=new schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=age type=INT properties=[kind=table table=raw schema=fruit]]",
    ]
    assert len(h.edges) == 3


def test__select_lateral_table_function(holder):
    sql = """
    CREATE TABLE fruit.new (name VARCHAR, age INT);
    INSERT INTO fruit.new (name, age)
    SELECT
        lat.name,
        r.age as age
    FROM fruit.raw r,
    LATERAL unnest(string_to_array(r.name, ',')) AS lat(name);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.paths == [
        [
            "column[fruit.raw.name]",
            "function[STRING_TO_ARRAY]",
            "function[UNNEST]",
            "column[lat.name]",
            "column[fruit.new.name]",
        ],
        [
            'literal[","]',
            "function[STRING_TO_ARRAY]",
            "function[UNNEST]",
            "column[lat.name]",
            "column[fruit.new.name]",
        ],
        [
            "column[fruit.raw.age]",
            "column[fruit.new.age]",
        ],
    ]
    assert h.nodes_full == [
        'literal[name="," type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]',
        "function[name=STRING_TO_ARRAY type=UNKNOWN position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "function[name=UNNEST type=UNKNOWN position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=name type=UNKNOWN properties=[kind=udtf table=lat]]",
        "column[name=age type=INT properties=[kind=table table=new schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=new schema=fruit]]",
        "column[name=age type=INT properties=[kind=table table=raw schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
    assert len(h.edges) == 6


def test__select_lateral_rows_from(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        INSERT INTO fruit.processed (name, age, kind, amount)
        SELECT x.*
        FROM fruit.raw r,
        LATERAL ROWS FROM
        (
            unnest(string_to_array(r.name, ',')),
            json_to_recordset('[{"a":40,"b":"foo"}]') AS (a INTEGER, b TEXT),
            generate_series(1, 3)
        ) AS x (name, age, kind, amount);
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token. Line 5, Col: 25.")


set_operations = ["EXCEPT", "INTERSECT", "UNION"]


@pytest.mark.parametrize("op", set_operations)
def test__select_union(holder, op):
    sql = f"""
    CREATE TABLE fruit.old (name VARCHAR);

    INSERT INTO fruit.processed (name)
    SELECT name FROM fruit.raw
    {op}
    SELECT name FROM fruit.old
    {op}
    SELECT 'hello' as name
    ;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.old.name]", "column[fruit.processed.name]"],
        ['literal["hello"]', "column[fruit.processed.name]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3


def test__select_table_as_table(holder):
    sql = """
    CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);
    CREATE TABLE t2(name1 VARCHAR, name2 VARCHAR, name3 VARCHAR);

    INSERT INTO t2 TABLE t1;
    CREATE VIEW t3 AS TABLE t2;     -- Not supported
    CREATE TABLE t4 AS TABLE t2;    -- Not supported
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[t1.name1]", "column[t2.name1]"], ["column[t1.name2]", "column[t2.name2]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2
    assert len(h.queries_original) == 3
    assert [TableQuery, TableQuery, InsertQuery] == h.query_types
    assert len(h.collected_queries.unsupported) == 2


def test__select_table_union_table_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);
        CREATE TABLE t2(name1 VARCHAR, name2 VARCHAR);
        CREATE TABLE t3(name1 VARCHAR, name2 VARCHAR);

        INSERT INTO t1 TABLE t2 UNION TABLE t3;
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token. Line 6, Col: 37.")


def test__select_order_by_in_string_add(holder):
    sql = """
    CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);
    CREATE TABLE t2(name1 VARCHAR, name2 VARCHAR, name3 VARCHAR);

    INSERT INTO t2 (name1)
    SELECT string_agg(name1, ',' ORDER BY name2) FROM t1;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[t1.name1]", "function[GROUP_CONCAT]", "column[t2.name1]"],
        ['literal[","]', "function[GROUP_CONCAT]", "column[t2.name1]"],
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3


def test__select_table_alias(holder):
    sql = """
    CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);

    INSERT INTO t1 (name1, name2)
    SELECT * FROM (SELECT 'A' AS a, 'B' AS b) AS t;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO t1 (name1, name2) SELECT t.a AS name1, t.b AS name2 FROM (SELECT 'A' AS a, 'B' AS b) AS t"
    )
    assert h.paths == [
        ['literal["A"]', "column[t.a]", "column[t1.name1]"],
        ['literal["B"]', "column[t.b]", "column[t1.name2]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


def test__select_table_alias_one_column(holder):
    sql = """
    CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);

    INSERT INTO t1 (name1, name2)
    SELECT * FROM (SELECT 'A' AS a, 'B' AS b) AS t(x);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO t1 (name1, name2) SELECT t.x AS name1, t.b AS name2 FROM (SELECT 'A' AS x, 'B' AS b) AS t"
    )
    assert h.paths == [
        ['literal["A"]', "column[t.x]", "column[t1.name1]"],
        ['literal["B"]', "column[t.b]", "column[t1.name2]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


# TODO:
#  CREATE TABLE a.b;
#  -- works, but should not; problem with trie
#  SELECT * FROM b;

# TODO: unnest([N...]) returns N columns named 'unnest', but sqlglot calls them 'offset'
#  Undo sqlglot's column renaming of {col} => {col}.offset
