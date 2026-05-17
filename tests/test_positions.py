import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

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
        'literal[1 type=INT query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]',
        'column[person.age type=INT kind=table]'
    ]
    assert h.paths == [['literal[1]', 'column[person.age]']]
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
        'column[person.age type=INT kind=table]',
        'column[person2.num type=INT kind=table]',
    ]
    assert h.paths == [['column[person2.num]', 'column[person.age]']]
    assert len(h.edges) == 1


def test__positions_values(holder):
    sql = """
    CREATE TABLE num (a INT, b INT);

    INSERT INTO num (a, b)
    VALUES (1, 1), (1, 1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        'literal[1 type=INT query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]',
        'literal[1 type=INT query_depth=1 query_width=1 statement=1 select=0 func_depth=0 func_arg=0]',
        'literal[1 type=INT query_depth=1 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]',
        'literal[1 type=INT query_depth=1 query_width=1 statement=1 select=1 func_depth=0 func_arg=0]',
        'column[num.a type=INT kind=table]', 'column[num.b type=INT kind=table]'
    ]
    assert h.paths == [
        ['literal[1]', 'column[num.a]'],
        ['literal[1]', 'column[num.a]'],
        ['literal[1]', 'column[num.b]'],
        ['literal[1]', 'column[num.b]']
    ]
    assert len(h.edges) == 4


def test__subquery_function(holder):
    sql = """
    CREATE TABLE person (age INT);
    CREATE TABLE person2 (num INT);

    INSERT INTO person (age)
    SELECT (SELECT COUNT(num) AS f FROM person2) AS age;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        'function[COUNT type=BIGINT query_depth=1 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        'column[person.age type=INT kind=table]',
        'column[person2.num type=INT kind=table]'
    ]
    assert h.paths == [['column[person2.num]', 'function[COUNT]', 'column[person.age]']]
    assert len(h.edges) == 2


def test__subquery_fail_union(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        CREATE TABLE person (age INT);

        INSERT INTO person (age)
        SELECT (SELECT 1 UNION SELECT 2);
        """
        h = holder(sql=sql, dialect=DIALECT)
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
        'literal[1 type=INT query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]',
        'literal[2 type=INT query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=1]',
        'function[ADD type=INT query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]',
        'column[person.age type=INT kind=table]'
    ]
    assert h.paths == [
        ['literal[1]', 'function[ADD]', 'column[person.age]'],
        ['literal[2]', 'function[ADD]', 'column[person.age]']
    ]
    assert len(h.edges) == 3


def test__subquery_fails_more_than_one_column(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = """
        CREATE TABLE person (age INT);
    
        INSERT INTO person (age)
        SELECT 1 + (SELECT 2 AS age, 3 as num) AS age;
        """
        h = holder(sql=sql, dialect=DIALECT)

    assert e.value.args[0] == "A subquery must return only one column"


def test__positions_duplicate_nested_functions(holder):
    sql = """
    CREATE TABLE names (name VARCHAR);

    INSERT INTO names (name)
    SELECT upper(current_user) || upper(current_user);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.nodes_full == [
     	'function[CURRENT_USER type=VARCHAR query_depth=0 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]',
     	'function[CURRENT_USER type=VARCHAR query_depth=0 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]',
     	'function[UPPER type=VARCHAR query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]',
     	'function[UPPER type=VARCHAR query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=1]',
        'function[DPIPE type=VARCHAR query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]',
        'column[names.name type=VARCHAR kind=table]',
    ]
    assert h.paths == [
        ['function[CURRENT_USER]', 'function[UPPER]', 'function[DPIPE]', 'column[names.name]'],
        ['function[CURRENT_USER]', 'function[UPPER]', 'function[DPIPE]', 'column[names.name]']
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 5
