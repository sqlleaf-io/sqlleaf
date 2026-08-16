import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest

from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import DeleteQuery, InsertQuery, MergeQuery, SelectQuery, UpdateQuery

DIALECT = "postgres"


def test__cte_nested(holder):
    sql = """
    WITH outer_cte AS (
        WITH inner_cte AS (
            SELECT name FROM fruit.raw
        )
        SELECT * FROM inner_cte
    )
    INSERT INTO fruit.processed
    SELECT * FROM outer_cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[inner_cte.name]", "column[outer_cte.name]", "column[fruit.processed.name]"]
    ]
    assert len(h.nodes) == 4
    assert len(h.edges) == 3


def test__cte_update_returning_with_old_and_new_aliases(holder):
    sql = """
    WITH first_cte AS (
        UPDATE fruit.raw
        SET name = 'pear'
        RETURNING old.age as age, new.age as new_age
    )
    UPDATE fruit.processed
    SET age = first_cte.age
    FROM first_cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.age]", "column[first_cte.age]", "column[fruit.processed.age]"],
        ['literal["pear"]', "column[fruit.raw.name]"],
    ]
    assert [UpdateQuery] == h.query_types
    assert [UpdateQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 5
    assert len(h.edges) == 3


def test__cte_fails_for_returning_unaliased_function(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        WITH first_cte AS (
            UPDATE fruit.raw
            SET name = 'pear'
            RETURNING upper(name)
        )
        INSERT INTO fruit.processed
        SELECT name
        FROM first_cte;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert (
        e.value.args[0]
        == "Non-column expression (UPPER(name)) must have an alias inside RETURNING to prevent ambiguity."
    )


def test__cte_fails_for_returning_ambiguous_aliases(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        WITH first_cte AS (
            UPDATE fruit.raw
            SET name = 'pear'
            RETURNING old.name, new.name
        )
        INSERT INTO fruit.processed
        SELECT name
        FROM first_cte;
        """
        holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert e.value.args[0] == "Column reference 'first_cte.name' is ambiguous (2 possible options)"


def test__select_complex_array_min(holder):
    sql = """
    CREATE TABLE target(age INT);

    INSERT INTO target (age)
    WITH data_source AS (
        SELECT CAST(ARRAY[10, -1, 5, 4.4] AS DECIMAL[]) AS my_array
    )
    SELECT (
        SELECT MIN(data_source.my_array[g.i]) AS min
        FROM GENERATE_SUBSCRIPTS(my_array, 1) AS g(i)
    )
    FROM data_source AS data_source;
    """
    holder(sql=sql, dialect=DIALECT)


def test__cte_two_updates_inside_update(holder):
    sql = """
    WITH first_cte AS (
        UPDATE fruit.raw
        SET name = 'pear'
        RETURNING age, old.age as old_age, new.age as new_age
    ),
    second_cte AS (
        UPDATE fruit.raw AS r
        SET name = 'tomato'
        RETURNING *, OLD.*, NEW.*
    )
    UPDATE fruit.processed
    SET age = first_cte.age
    FROM first_cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
    h.lineage.print_tree()

    assert h.paths == [
        ["column[fruit.raw.age]", "column[first_cte.age]", "column[fruit.processed.age]"],
        ['literal["pear"]', "column[fruit.raw.name]"],
        ['literal["tomato"]', "column[fruit.raw.name]"],
    ]
    assert [UpdateQuery] == h.query_types
    assert [UpdateQuery, UpdateQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


def test__cte_delete_inside_insert(holder):
    sql = """
    WITH cte AS (
        DELETE FROM fruit.raw
        RETURNING *
    )
    INSERT INTO fruit.processed (name)
    SELECT name
    FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[cte.name]", "column[fruit.processed.name]"],
    ]
    assert [InsertQuery] == h.query_types
    assert [DeleteQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 3
    assert len(h.edges) == 2


def test__cte_insert_inside_delete(holder):
    sql = """
    WITH cte AS (
        INSERT INTO fruit.raw (name)
        SELECT 'hello' AS name
        RETURNING *
    )
    DELETE FROM fruit.processed p
    USING cte AS c
    WHERE p.name = c.name
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["hello"]', "column[fruit.raw.name]"],
    ]
    assert [DeleteQuery] == h.query_types
    assert [InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 2
    assert len(h.edges) == 1


def test__cte_delete_inside_delete(holder):
    sql = """
    WITH cte AS (
        DELETE FROM fruit.raw
        RETURNING *
    )
    DELETE FROM fruit.processed p
    USING cte AS c
    WHERE p.name = c.name
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == []
    assert [DeleteQuery] == h.query_types
    assert [DeleteQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 0
    assert len(h.edges) == 0


def test__cte_merge_inside_select(holder):
    sql = """
    WITH cte AS (
        MERGE INTO fruit.processed AS t
        USING fruit.raw AS s
        ON t.kind = s.kind
        WHEN MATCHED THEN
            UPDATE SET name = s.name
        WHEN NOT MATCHED THEN
            INSERT (label) VALUES (s.kind)
        RETURNING merge_action() as action, t.*
    )
    SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.kind]", "column[fruit.processed.label]"],
    ]
    assert [SelectQuery] == h.query_types
    assert [MergeQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert [UpdateQuery, InsertQuery] == list(
        map(type, [ch.original for ch in h.holders[0].downstream_holders[0].downstream_holders])
    )
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__cte_merge_inside_insert(holder):
    sql = """
    CREATE TABLE fruit (name VARCHAR, kind VARCHAR);
    CREATE TABLE drink (name2 VARCHAR, kind2 VARCHAR);
    CREATE TABLE fruit_drink (action VARCHAR, name VARCHAR, kind VARCHAR, name2 VARCHAR, kind2 VARCHAR);

    WITH cte AS (
        MERGE INTO fruit AS t
        USING drink AS s
        ON t.name = s.name2
        WHEN MATCHED THEN
            UPDATE SET name = s.name2
        WHEN NOT MATCHED THEN
            INSERT (kind) VALUES (s.kind2)
        RETURNING merge_action() as action, *
    )
    INSERT INTO fruit_drink
    SELECT *
    FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=False)

    assert h.paths == [
        ["function[MERGE_ACTION]", "column[cte.action]", "column[fruit_drink.action]"],
        ["column[drink.name2]", "column[fruit.name]", "column[cte.name]", "column[fruit_drink.name]"],
        ["column[drink.name2]", "column[cte.name2]", "column[fruit_drink.name2]"],
        ["column[drink.kind2]", "column[fruit.kind]", "column[cte.kind]", "column[fruit_drink.kind]"],
        ["column[drink.kind2]", "column[cte.kind2]", "column[fruit_drink.kind2]"],
    ]
    assert (
        h.holders[3].transformed.statement.sql(dialect=DIALECT) == "WITH cte AS ("
        "SELECT MERGE_ACTION() AS action, t.name AS name, t.kind AS kind, s.name2 AS name2, "
        "s.kind2 AS kind2 FROM fruit AS t JOIN drink AS s ON s.name2 = t.name) "
        "INSERT INTO fruit_drink (action, name, kind, name2, kind2) "
        "SELECT cte.action AS action, cte.name AS name, cte.kind AS kind, cte.name2 AS name2, cte.kind2 AS kind2 "
        "FROM cte AS cte"
    )
    assert len(h.nodes) == 15
    assert len(h.edges) == 12


def test__cte_merge_with_update_and_insert(holder):
    sql = """
    WITH merge_cte AS (
        SELECT kind, name
        FROM fruit.raw
    )
    MERGE INTO fruit.processed AS t
    USING merge_cte AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN
        UPDATE SET name = s.name
    WHEN NOT MATCHED THEN
        INSERT (label) VALUES (s.kind);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[merge_cte.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.kind]", "column[merge_cte.kind]", "column[fruit.processed.label]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.queries_original) == 1
    assert [UpdateQuery, InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))


def test__cte_insert_inside_insert(holder):
    sql = """
    WITH insert_cte AS (
        INSERT INTO fruit.raw as r (name)
        SELECT 'orange' as name
        RETURNING name, kind
    )
    INSERT INTO fruit.processed (name, kind)
    SELECT name, kind FROM insert_cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.kind]", "column[insert_cte.kind]", "column[fruit.processed.kind]"],
        ['literal["orange"]', "column[fruit.raw.name]", "column[insert_cte.name]", "column[fruit.processed.name]"],
    ]
    assert [InsertQuery] == h.query_types
    assert [InsertQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 7
    assert len(h.edges) == 5


def test__cte_insert_inside_insert_conflict_returning(holder):
    sql = """
    WITH insert_cte AS (
        INSERT INTO fruit.raw (name)
        VALUES ('pear')
        ON CONFLICT (name)
        DO UPDATE SET
            name = LOWER(EXCLUDED.name)
        RETURNING name, 'pear' as kind
    )
    INSERT INTO fruit.processed (name, kind, label)
    SELECT name, kind, 'pear' as label FROM insert_cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ['literal["pear"]', "column[insert_cte.kind]", "column[fruit.processed.kind]"],
        ['literal["pear"]', "column[fruit.processed.label]"],
        ['literal["pear"]', "column[fruit.raw.name]", "column[insert_cte.name]", "column[fruit.processed.name]"],
        [
            'literal["pear"]',
            "function[LOWER]",
            "column[fruit.raw.name]",
            "column[insert_cte.name]",
            "column[fruit.processed.name]",
        ],
    ]
    assert len(h.nodes) == 11
    assert len(h.edges) == 8


def test__cte_insert_and_update_inside_select(holder):
    sql = """
    WITH insert_cte AS (
        INSERT INTO fruit.raw (name)
        SELECT 'orange' as name
        RETURNING fruit.raw.name, name, *
    ),
    update_cte AS (
        UPDATE fruit.raw AS r
        SET name = 'banana'
    )
    SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [['literal["orange"]', "column[fruit.raw.name]"], ['literal["banana"]', "column[fruit.raw.name]"]]
    assert [SelectQuery] == h.query_types
    assert [InsertQuery, UpdateQuery] == list(map(type, [ch.original for ch in h.holders[0].downstream_holders]))
    assert len(h.nodes) == 3
    assert len(h.edges) == 2


#
# # TODO: requires new algorithm
# def test__cte_recursive_view(holder):
#     sql = """
#     WITH RECURSIVE numbers AS (
#         SELECT 1 AS n
#         UNION ALL
#         SELECT n + 1 AS n
#         FROM numbers
#         WHERE n < 5
#     )
#     INSERT INTO fruit.processed (age)
#     SELECT n AS age FROM numbers;
#     """
#     h = holder(sql=sql, dialect=DIALECT, with_tables=True)
#
#     assert h.paths == [
#         [
#             "literal[1 type=INT query_depth=1 statement=0 select=0 func_depth=0 func_arg=0]",
#             "column[numbers.n type=INT kind=cte member=anchor statement=0]",
#             "column[fruit.processed.age type=INT ]",
#         ],
#         [
#             "literal[1 type=INT query_depth=1 statement=0 select=0 func_depth=0 func_arg=0]",
#             "column[numbers.n type=INT kind=cte member=anchor statement=0]",
#             "function[ADD type=INT query_depth=1 statement=0 select=0 func_depth=0 func_arg=0]",
#             "column[numbers.n type=INT kind=cte member=recursive statement=0]",
#             "column[fruit.processed.age type=INT ]",
#         ],
#         [
#             "literal[1 type=INT query_depth=1 statement=0 select=0 func_depth=1 func_arg=1]",
#             "function[ADD type=INT query_depth=1 statement=0 select=0 func_depth=0 func_arg=0]",
#             "column[numbers.n type=INT kind=cte member=recursive statement=0]",
#             "column[fruit.processed.age type=INT ]",
#         ],
#     ]

# TODO
# Recursive CTE with multiple anchor members — e.g. SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT n+1 FROM cte
# Recursive CTE referencing itself multiple times — SELECT a.n + b.n FROM cte a, cte b
# CTE used in multiple places — WITH cte AS (...) INSERT INTO x SELECT FROM cte JOIN cte
# CTE with UNION inside — a CTE whose body is a UNION (not recursive)


def test__cte_materialized(holder):
    sql = """
    WITH cte AS MATERIALIZED (
        SELECT 1 AS n
    )
    INSERT INTO fruit.processed (age)
    SELECT n AS age FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [["literal[1]", "column[cte.n]", "column[fruit.processed.age]"]]
    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=0 select=0 func_depth=0 func_arg=0]]",
        "column[name=n type=INT properties=[kind=cte subkind=materialized table=cte statement=0]]",
        "column[name=age type=INT properties=[kind=table table=processed schema=fruit]]",
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2
