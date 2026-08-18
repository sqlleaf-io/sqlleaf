import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"

"""
Test the positions of each expression in the graph.
"""

select_ones = [
    "SELECT 1",
    "(SELECT 1)",
    "((SELECT 1))",
]


@pytest.mark.parametrize("substr", select_ones)
def test__subquery(holder, substr):
    sql = f"""
    CREATE TABLE person (age INT);

    INSERT INTO person (age)
    SELECT ({substr})
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=person]]",
    ]
    assert h.paths == [["literal[1]", "column[person.age]"]]
    assert len(h.edges) == 1


def test__subquery_from(holder):
    sql = """
    CREATE TABLE person (age INT);
    CREATE TABLE person2 (num INT);

    INSERT INTO person (age)
    SELECT * FROM (SELECT * FROM person2) as p;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "column[name=age type=INT properties=[kind=table table=person]]",
        "column[name=num type=INT properties=[kind=table table=person2]]",
    ]
    assert h.paths == [["column[person2.num]", "column[person.age]"]]
    assert len(h.edges) == 1


def test__positions_values(holder):
    sql = """
    CREATE TABLE num (a INT, b INT);

    INSERT INTO num (a, b)
    VALUES (1, 1), (1, 1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO num (a, b) SELECT 1 AS a, 1 AS b UNION ALL SELECT 1 AS a, 1 AS b"
    )

    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "literal[name=1 type=INT position=[query_depth=1 query_width=1 statement=1 select=0 func_depth=0 func_arg=0]]",
        "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]",
        "literal[name=1 type=INT position=[query_depth=1 query_width=1 statement=1 select=1 func_depth=0 func_arg=0]]",
        "column[name=a type=INT properties=[kind=table table=num]]",
        "column[name=b type=INT properties=[kind=table table=num]]",
    ]
    assert h.paths_full == [
        [
            "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
            "column[name=a type=INT properties=[kind=table table=num]]",
        ],
        [
            "literal[name=1 type=INT position=[query_depth=1 query_width=1 statement=1 select=0 func_depth=0 func_arg=0]]",
            "column[name=a type=INT properties=[kind=table table=num]]",
        ],
        [
            "literal[name=1 type=INT position=[query_depth=1 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]",
            "column[name=b type=INT properties=[kind=table table=num]]",
        ],
        [
            "literal[name=1 type=INT position=[query_depth=1 query_width=1 statement=1 select=1 func_depth=0 func_arg=0]]",
            "column[name=b type=INT properties=[kind=table table=num]]",
        ],
    ]
    assert len(h.edges) == 4


def test__positions_cte_swapped(holder):
    sql = """
    CREATE TABLE num (a INT, b INT, c INT);

    WITH cte AS (
        SELECT 'a' AS a, 'a' AS b
    )
    INSERT INTO num (a, b, c)
    SELECT 'a' AS a, cte.b AS b, cte.a AS c FROM cte;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert (
        h.holders[1].transformed.statement.sql(dialect=DIALECT)
        == "WITH cte AS (SELECT 'a' AS a, 'a' AS b) INSERT INTO num (a, b, c) SELECT 'a' AS a, cte.b AS b, cte.a AS c FROM cte AS cte"
    )
    assert h.nodes_full == [
        'literal[name="a" type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
        'literal[name="a" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]',
        'literal[name="a" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
        "column[name=a type=VARCHAR properties=[kind=cte table=cte statement=1]]",
        "column[name=b type=VARCHAR properties=[kind=cte table=cte statement=1]]",
        "column[name=a type=INT properties=[kind=table table=num]]",
        "column[name=b type=INT properties=[kind=table table=num]]",
        "column[name=c type=INT properties=[kind=table table=num]]",
    ]
    assert h.paths_full == [
        [
            'literal[name="a" type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
            "column[name=a type=INT properties=[kind=table table=num]]",
        ],
        [
            'literal[name="a" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]',
            "column[name=b type=VARCHAR properties=[kind=cte table=cte statement=1]]",
            "column[name=b type=INT properties=[kind=table table=num]]",
        ],
        [
            'literal[name="a" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
            "column[name=a type=VARCHAR properties=[kind=cte table=cte statement=1]]",
            "column[name=c type=INT properties=[kind=table table=num]]",
        ],
    ]


def test__subquery_function(holder):
    sql = """
    CREATE TABLE person (age INT);
    CREATE TABLE person2 (num INT);

    INSERT INTO person (age)
    SELECT (SELECT COUNT(num) AS f FROM person2) AS age;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "function[name=COUNT type=BIGINT position=[query_depth=1 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=person]]",
        "column[name=num type=INT properties=[kind=table table=person2]]",
    ]
    assert h.paths == [["column[person2.num]", "function[COUNT]", "column[person.age]"]]
    assert len(h.edges) == 2


def test__subquery_fail_union(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        CREATE TABLE person (age INT);

        INSERT INTO person (age)
        SELECT (SELECT 1 UNION SELECT 2);
        """
        holder(sql=sql, dialect=DIALECT)
        print()

    assert e.value.args[0] == "A subquery must return only one column"


def test__subquery_as_function_argument(holder):
    sql = """
    CREATE TABLE person (age INT);

    INSERT INTO person (age)
    SELECT 1 + (SELECT 2 AS age) AS age;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "literal[name=2 type=INT position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=1]]",
        "function[name=ADD type=INT position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=table table=person]]",
    ]
    assert h.paths == [
        ["literal[1]", "function[ADD]", "column[person.age]"],
        ["literal[2]", "function[ADD]", "column[person.age]"],
    ]
    assert len(h.edges) == 3


def test__subquery_fails_more_than_one_column(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        CREATE TABLE person (age INT);

        INSERT INTO person (age)
        SELECT 1 + (SELECT 2 AS age, 3 as num) AS age;
        """
        holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0] == "A subquery must return only one column"


def test__positions_duplicate_nested_functions(holder):
    sql = """
    CREATE TABLE names (name VARCHAR);

    INSERT INTO names (name)
    SELECT upper(current_user) || upper(current_user);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.nodes_full == [
        "function[name=CURRENT_USER type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]",
        "function[name=CURRENT_USER type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]",
        "function[name=UPPER type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "function[name=UPPER type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=1]]",
        "function[name=DPIPE type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "column[name=name type=VARCHAR properties=[kind=table table=names]]",
    ]
    assert h.paths == [
        ["function[CURRENT_USER]", "function[UPPER]", "function[DPIPE]", "column[names.name]"],
        ["function[CURRENT_USER]", "function[UPPER]", "function[DPIPE]", "column[names.name]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5
