import os
import sys

import pytest

from sqlleaf.objects.query_types import TableQuery, InsertQuery

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import sqlglot

from tests.new_fixtures import holder, is_subset, DIALECT

DIALECT = "postgres"

# TODO: unnest([N...]) returns N columns named 'unnest', but sqlglot calls them 'offset'
#  We need to throw an error if unnest() is called without specific column selection.
#  We also need to undo sqlglot's column renaming of {col} => {col}.offset
"""
SELECT * FROM unnest(ARRAY['apple', 'banana']);                             -- Invalid
SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY;             -- Invalid
SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY AS t(a,b);   -- Valid        but sqlglot sets fruit => fruit.offset
SELECT fruit FROM unnest(ARRAY['apple', 'banana']);                         -- Valid        but sqlglot sets fruit => fruit.offset
"""


@pytest.mark.skip(reason="todo")
def test__select_with_ordinality(holder):
    queries = """
    INSERT INTO fruit.processed
    SELECT * FROM unnest(ARRAY['apple', 'banana']) WITH ORDINALITY AS t(name, age);
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()


def test__select_values(holder):
    queries = """
    INSERT INTO fruit.processed (name, kind)
    SELECT * FROM (VALUES (1, 'one'), (2, 'two')) AS t (num, letter);
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ["literal[1]", "column[t.num]", "column[fruit.processed.name]"],
        ["literal[2]", "column[t.num]", "column[fruit.processed.name]"],
        ['literal["one"]', "column[t.letter]", "column[fruit.processed.kind]"],
        ['literal["two"]', "column[t.letter]", "column[fruit.processed.kind]"],
    ]
    assert "column[t.letter type=VARCHAR kind=derived_table]" in nodes
    assert len(nodes) == 8
    assert len(edges) == 6


def test__select_dpipe_cte(holder):
    queries = """
    WITH cte AS (
        SELECT 'hello' AS other
    )
    INSERT INTO fruit.processed (kind)
    SELECT
        c.other || c.other as kind
    FROM cte AS c
    ;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == 2 * [
        ['literal["hello"]', 'column[cte.other]', 'function[DPIPE()]', 'column[fruit.processed.kind]']
    ]
    assert len(nodes) == 4
    assert len(edges) == 4


def test__select_dpipe(holder):
    queries = """
    INSERT INTO fruit.processed (kind)
    SELECT
        name || r.name || upper(r.name) as kind
    FROM fruit.raw AS r
    ;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    # a || b || c  ->  (a || b) || c
    #                     ^     ^
    #                  DPIPE1  DPIPE2
    #
    # expect: a -> dpipe1 -> dpipe2
    # expect: b -> dpipe1 -> dpipe2
    # expect: c -> dpipe2

    assert paths == 2 * [
        ["column[fruit.raw.name]", "function[DPIPE()]", "function[DPIPE()]", "column[fruit.processed.kind]"],
    ] + [["column[fruit.raw.name]", "function[UPPER()]", "function[DPIPE()]", "column[fruit.processed.kind]"]]
    assert len(nodes) == 5
    assert len(edges) == 6


def test__select_case(holder):
    queries = """
    INSERT INTO fruit.processed (age, number)
    SELECT
        CASE WHEN name = 'John' THEN 1 ELSE 2 END AS age,
        CASE WHEN name = 'John' THEN
            CASE WHEN age > 10 THEN 5 END
        ELSE 6 END AS number
    FROM fruit.raw;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ['literal[2]', 'column[fruit.processed.age]'],
        ['literal[1]', 'column[fruit.processed.age]'],
        ['literal[6]', 'column[fruit.processed.number]'],
        ['null[NULL]', 'column[fruit.processed.number]'],
        ['literal[5]', 'column[fruit.processed.number]']
    ]
    assert len(nodes) == 7
    assert len(edges) == 5


# TODO: ROW is a value constructor, not UDF - add to sqlglot
def test__select_row(holder):
    queries = """
    INSERT INTO fruit.processed (name)
    SELECT ROW(r.name, r.kind) AS name
    FROM fruit.raw AS r;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ['column[fruit.raw.name]', 'udf[ROW()]', 'column[fruit.processed.name]'], ['column[fruit.raw.kind]', 'udf[ROW()]', 'column[fruit.processed.name]']
    ]
    assert len(nodes) == 4
    assert len(edges) == 3


def test__select_cast(holder):
    queries = """
    INSERT INTO fruit.processed (age)
    SELECT name::int AS age
    FROM fruit.raw;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [['column[fruit.raw.name]', 'function[CAST()]', 'column[fruit.processed.age]']]
    assert nodes == [
        'function[CAST() type=INT query_depth=0 statement=0 select=0 func_depth=0 func_arg=0]',
        'column[fruit.processed.age type=INT kind=table]',
        'column[fruit.raw.name type=VARCHAR kind=table]',
    ]
    assert len(edges) == 2


def test__select_filter_and_where(holder):
    queries = """
    INSERT INTO fruit.processed (age, amount)
    SELECT
        SUM(age) FILTER (WHERE name = 'John') AS age,
        COUNT(*) FILTER (WHERE CURRENT_USER = 'john') AS amount
    FROM fruit.raw;

    INSERT INTO fruit.processed (age)
    SELECT 1 AS age
    WHERE CURRENT_USER = 'john';
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['column[fruit.raw.age]', 'function[SUM()]', 'column[fruit.processed.age]'],
        ['star[*]', 'function[COUNT()]', 'column[fruit.processed.amount]'],
        ['literal[1]', 'column[fruit.processed.age]']
    ]
    assert len(nodes) == 7
    assert len(edges) == 5
    # Ensure the FILTER is dropped
    assert queries[0].statement_transformed.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (age, amount) SELECT SUM(raw.age) AS age, COUNT(*) AS amount FROM fruit.raw AS raw"
    # Ensure the WHERE is dropped
    assert queries[1].statement_transformed.sql(dialect=DIALECT) == "INSERT INTO fruit.processed (age) SELECT 1 AS age"


def test__select_hidden_system_columns(holder):
    queries = """
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
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ['literal["hello"]', "column[fruit.new.name]"],
        ["column[fruit.new.xmax]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
        ["column[fruit.raw.xmax]", "column[fruit.processed.amount]"],
        ["column[fruit.raw.xmax]", "column[fruit.processed.number]"],
    ]
    assert "column[fruit.new.xmax type=OID kind=table]" in nodes
    assert len(nodes) == 9
    assert len(edges) == 5


def test__select_fails_unknown_column(holder):
    with pytest.raises(sqlglot.errors.OptimizeError) as e:
        queries = """
        INSERT INTO fruit.processed (name)
        SELECT hello
        FROM fruit.raw;
        """
        h = holder(with_tables=True)
        h.generate(queries, dialect=DIALECT)

    assert e.value.args[0].startswith("Column 'hello' could not be resolved.")


tests = [
    ("-10", "literal"),
    ("10", "literal"),
    ("TRUE", "literal"),
    (
        "NULL",
        "null",
    ),
    ("LOCALTIME()", "function"),
    ("MY.FUNC()", "udf"),
]


@pytest.mark.parametrize("case", tests)
def test__select_value_twice(holder, case):
    value, kind = case
    queries = f"""
    INSERT INTO fruit.processed (name, age)
    SELECT {value} as name, {value} as age;
    """
    print(queries)
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        [f"{kind}[{value}]", "column[fruit.processed.name]"],
        [f"{kind}[{value}]", "column[fruit.processed.age]"],
    ]
    assert len(nodes) == 4
    assert len(edges) == 2


# TODO: select_query_twice
# TODO: select_query_twice, but slightly different second


def test__select_window_function(holder):
    queries = """
    INSERT INTO fruit.processed (amount, age)
    SELECT 
        ROW_NUMBER() OVER (ORDER BY name DESC) AS amount,
        RANK() OVER (PARTITION BY age ORDER BY kind) AS age
    FROM fruit.raw;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    assert paths == [
        ["window[RANK()]", "column[fruit.processed.age]"],
        ["window[ROW_NUMBER()]", "column[fruit.processed.amount]"],
    ]
    assert len(nodes) == 4
    assert len(edges) == 2


def test__select_join_to_self(holder):
    queries = """
    INSERT INTO fruit.processed (name, age, kind)
    SELECT
        p.name,
        r.age as age,
        color
    FROM fruit.raw r
    INNER JOIN fruit.processed p ON r.name = p.name;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    assert paths == [
        # ['column[fruit.processed.name]', 'column[fruit.processed.name]'],
        ["column[fruit.raw.color]", "column[fruit.processed.kind]"],
        ["column[fruit.raw.age]", "column[fruit.processed.age]"],
        # Don't exclude self-referential inserts
    ]
    assert len(nodes) == 5
    assert len(edges) == 3


def test__select_assorted(holder):
    queries = """
    CREATE TABLE anything(name1 VARCHAR, name2 VARCHAR);

    INSERT INTO anything
    SELECT
        ARRAY[1,2,3] as name1,
        INTERVAL '-10.75 MINUTE' as name2;

    INSERT INTO anything SELECT 1;
    """
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    assert is_subset(
        subarr=[
            "literal[{1,2,3} type=ARRAY<INT> query_depth=0 statement=1 select=0 func_depth=0 func_arg=0]",
            'interval["-10.75 MINUTE" type=INTERVAL query_depth=0 statement=1 select=1 func_depth=0 func_arg=0]',
        ],
        arr=nodes,
    )
    assert len(nodes) == 5
    assert len(edges) == 3


# TODO: add JSON_TO_RECORDSET() as a Postgres functions in sqlglot
def test__select_rows_from(holder):
    queries = """
    INSERT INTO fruit.processed (name, age, kind, amount)
    SELECT *
    FROM ROWS FROM
        (
            unnest(ARRAY['x', 'y']),
            json_to_recordset('[{"a":40,"b":"foo"}]')
                AS y(a INTEGER, b TEXT),
            generate_series(1, 3)
        ) AS x (name, age, kind, amount)
    ORDER BY age;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    assert paths == [
        ['literal[{"x","y"}]', "function[UNNEST()]", "column[x.name]", "column[fruit.processed.name]"],
        ['literal["[{"a":40,"b":"foo"}]"]', "udf[JSON_TO_RECORDSET()]", "column[y.b]", "column[x.kind]", "column[fruit.processed.kind]"],
        ['literal["[{"a":40,"b":"foo"}]"]', "udf[JSON_TO_RECORDSET()]", "column[y.a]", "column[x.age]", "column[fruit.processed.age]"],
        ["literal[1]", "function[EXPLODINGGENERATESERIES()]", "column[x.amount]", "column[fruit.processed.amount]"],
        ["literal[3]", "function[EXPLODINGGENERATESERIES()]", "column[x.amount]", "column[fruit.processed.amount]"],
    ]
    assert is_subset(
        subarr=[
            # TODO: fix type
            "column[x.age type=UNKNOWN kind=derived_table]",
            "column[y.a type=INT kind=derived_table]",
        ],
        arr=nodes,
    )
    # TODO: duplicate nodes (literals and udfs)
    # assert len(nodes) == 17     # Correct

    assert len(nodes) == 19
    assert len(edges) == 15


# TODO: sqlglot parser breaks on 'LATERAL ROWS FROM'
# TODO: support ROWS FROM without table alias


# TODO: test below query
@pytest.mark.skip(reason="todo")
def test__select_lateral(holder):
    queries = """
    SELECT u.name, task.title
    FROM users u,
    LATERAL get_tasks_for_user(u.id) AS task(title, due_date);
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    assert paths == []


set_operations = ["EXCEPT", "INTERSECT", "UNION"]


@pytest.mark.parametrize("op", set_operations)
def test__select_union(holder, op):
    queries = f"""
    CREATE TABLE fruit.old (name VARCHAR);

    INSERT INTO fruit.processed (name)
    SELECT name FROM fruit.raw
    {op}
    SELECT name FROM fruit.old
    {op}
    SELECT 'hello' as name
    ;
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    edges = h.get_edges()
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()

    assert paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.old.name]", "column[fruit.processed.name]"],
        ['literal["hello"]', "column[fruit.processed.name]"],
    ]
    assert len(nodes) == 4
    assert len(edges) == 3


def test__select_table(holder):
    queries = """
    CREATE TABLE t1(name1 VARCHAR, name2 VARCHAR);
    CREATE TABLE t2(name1 VARCHAR, name2 VARCHAR, name3 VARCHAR);

    INSERT INTO t2 TABLE t1;
    CREATE VIEW t3 AS TABLE t2;     -- Not supported
    CREATE TABLE t4 AS TABLE t2;    -- Not supported
    """
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert paths == [
        ['column[t1.name1]', 'column[t2.name1]'],
        ['column[t1.name2]', 'column[t2.name2]']
    ]
    assert len(nodes) == 4
    assert len(edges) == 2
    assert len(queries) == 3
    assert [TableQuery, TableQuery, InsertQuery] == list(map(type, queries))
