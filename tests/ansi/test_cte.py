from sqlleaf.models.query import InsertQuery
from tests.new_fixtures import holder as holder

DIALECT = ""


def test__cte_simple(holder):
    sql = """
    WITH cte_names AS (
        SELECT
            lower(age) as age,
            'hello' as name
        FROM fruit.raw r
    )
    INSERT INTO fruit.processed (name, age)
    SELECT
        name,
        age
    FROM cte_names;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["hello"]', "column[cte_names.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "function[LOWER]", "column[cte_names.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__cte_with_values(holder):
    sql = """
    WITH cte (age, name) AS (
        VALUES (1, 'apple'), (2, 'banana')
    )
    INSERT INTO fruit.processed (age, name)
    SELECT * FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    expected = "WITH cte(age, name) AS (SELECT 1 AS age, 'apple' AS name UNION ALL SELECT 2 AS age, 'banana' AS name) INSERT INTO fruit.processed (age, name) SELECT cte.age AS age, cte.name AS name FROM cte AS cte"
    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == expected
    assert h.paths == [
        ['literal["apple"]', "column[cte.name]", "column[fruit.processed.name]"],
        ['literal["banana"]', "column[cte.name]", "column[fruit.processed.name]"],
        ["literal[1]", "column[cte.age]", "column[fruit.processed.age]"],
        ["literal[2]", "column[cte.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 8
    assert len(h.edges) == 6


def test__cte_with_union(holder):
    sql = """
    WITH cte (age, name) AS (
        SELECT 1 AS age, 'apple' AS name
        UNION
        SELECT 2 AS age, 'banana' AS name
    )
    INSERT INTO fruit.processed (age, name)
    SELECT * FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    expected = "WITH cte(age, name) AS (SELECT 1 AS age, 'apple' AS name UNION SELECT 2 AS age, 'banana' AS name) INSERT INTO fruit.processed (age, name) SELECT cte.age AS age, cte.name AS name FROM cte AS cte"
    assert h.holders[0].transformed.statement.sql(dialect=DIALECT) == expected

    assert h.paths == [
        ['literal["apple"]', "column[cte.name]", "column[fruit.processed.name]"],
        ['literal["banana"]', "column[cte.name]", "column[fruit.processed.name]"],
        ["literal[1]", "column[cte.age]", "column[fruit.processed.age]"],
        ["literal[2]", "column[cte.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 8
    assert len(h.edges) == 6


def test__cte_inside_select(holder):
    sql = """
    CREATE TABLE target(age INT);
    INSERT INTO target (age) SELECT (
        WITH cte AS (
            SELECT 'Hello Alice' AS msg
        )
        SELECT msg FROM cte
    ) AS age;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    assert h.paths == [['literal["Hello Alice"]', "column[cte.msg]", "column[target.age]"]]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2


def test__cte_named_columns(holder):
    sql = """
    WITH cte_names(col2, col1) AS (
        SELECT
            lower(age) as age,
            'hello' as name
        FROM fruit.raw r
    )
    INSERT INTO fruit.processed (name, age)
    SELECT
        col1,
        col2
    FROM cte_names;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["hello"]', "column[cte_names.col1]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "function[LOWER]", "column[cte_names.col2]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__cte_duplicate_columns(holder):
    sql = """
    WITH cte_names AS (
        SELECT 1 as number
    )
    INSERT INTO fruit.processed (age)
    SELECT c.number + c.number AS age
    FROM cte_names c;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[1]", "column[cte_names.number]", "function[ADD]", "column[fruit.processed.age]"],
        ["literal[1]", "column[cte_names.number]", "function[ADD]", "column[fruit.processed.age]"],
    ]
    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "function[name=ADD type=INT position=[query_depth=0 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=number type=INT properties=[kind=cte table=cte_names statement=0]]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
    ]
    assert len(h.edges) == 4


def test__cte_join_same_names(holder):
    sql = """
    CREATE TABLE fruit.old (kind VARCHAR);

    WITH cte_names AS (
        SELECT
            LOWER(r.kind || o.kind) as kind
        FROM fruit.raw r
        INNER JOIN fruit.old o
        ON r.kind = o.kind
    )
    INSERT INTO fruit.processed (kind)
    SELECT
        kind
    FROM cte_names;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        [
            "column[fruit.raw.kind]",
            "function[DPIPE]",
            "function[LOWER]",
            "column[cte_names.kind]",
            "column[fruit.processed.kind]",
        ],
        [
            "column[fruit.old.kind]",
            "function[DPIPE]",
            "function[LOWER]",
            "column[cte_names.kind]",
            "column[fruit.processed.kind]",
        ],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5


def test__cte_same_functions_different_levels(holder):
    sql = """
    WITH cte_names AS (
        SELECT
            'hello' as not_used,
            'a' as a_name,
            LOWER('a') as a_name1,
            1 as ignored
    )
    INSERT INTO fruit.processed (name, name1, name2, name3)
    SELECT
        'a' as name,
        LOWER('a') as name1,
        LOWER(cte_names.a_name) as name2,
        LOWER(LOWER(cte_names.a_name1)) as name3
    FROM cte_names;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["a"]', "column[fruit.processed.name]"],
        ['literal["a"]', "function[LOWER]", "column[fruit.processed.name1]"],
        ['literal["a"]', "column[cte_names.a_name]", "function[LOWER]", "column[fruit.processed.name2]"],
        [
            'literal["a"]',
            "function[LOWER]",
            "column[cte_names.a_name1]",
            "function[LOWER]",
            "function[LOWER]",
            "column[fruit.processed.name3]",
        ],
    ]
    assert len(h.nodes) == 15
    assert len(h.edges) == 11


def test__cte_two_identical(holder):
    sql = """
    WITH cte1 AS (SELECT 'a' as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;

    WITH cte1 AS (SELECT 'a' as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [['literal["a"]', "column[cte1.name]", "column[fruit.processed.name]"]]
    assert [InsertQuery] == h.query_types
    assert len(h.nodes) == 3
    assert len(h.edges) == 2


def test__cte_two_same_name_different_query(holder):
    sql = """
    WITH cte1 AS (SELECT 1 as name)
    INSERT INTO fruit.processed
    SELECT c.name as name
    FROM cte1 c;

    WITH cte1 AS (SELECT 2 as name)
    INSERT INTO fruit.raw
    SELECT c.name as name
    FROM cte1 c;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["literal[1]", "column[cte1.name]", "column[fruit.processed.name]"],
        ["literal[2]", "column[cte1.name]", "column[fruit.raw.name]"],
    ]
    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "literal[name=2 type=INT position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=name type=INT properties=[kind=cte table=cte1 statement=0]]",
        "column[name=name type=INT properties=[kind=cte table=cte1 statement=1]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit]]",
    ]
    assert [InsertQuery, InsertQuery] == h.query_types
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


def test__cte_chained(holder):
    sql = """
    WITH cte_one AS (
        SELECT name FROM fruit.raw
    ),
    cte_two AS (
        SELECT * FROM cte_one
    )
    INSERT INTO fruit.processed
    SELECT * FROM cte_two;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[cte_one.name]", "column[cte_two.name]", "column[fruit.processed.name]"]
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3


def test__cte_chained_many_to_one(holder):
    sql = """
    WITH single AS (
        SELECT '1' as name, '2' as kind
    ),
    multiple AS (
        SELECT name || kind AS name, name AS label FROM single
    )
    INSERT INTO fruit.processed (name, label)
    SELECT name, label FROM multiple;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["1"]', "column[single.name]", "column[multiple.label]", "column[fruit.processed.label]"],
        [
            'literal["1"]',
            "column[single.name]",
            "function[DPIPE]",
            "column[multiple.name]",
            "column[fruit.processed.name]",
        ],
        [
            'literal["2"]',
            "column[single.kind]",
            "function[DPIPE]",
            "column[multiple.name]",
            "column[fruit.processed.name]",
        ],
    ]
    assert len(h.nodes) == 9
    assert len(h.edges) == 8
