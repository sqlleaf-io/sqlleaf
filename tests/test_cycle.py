import os
import sys

import pytest

from sqlleaf.exception import SqlLeafException

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from tests.new_fixtures import holder

DIALECT = "postgres"

create_letter_table = "CREATE TABLE letter (a VARCHAR, b VARCHAR, c VARCHAR, d VARCHAR);"

# test: A -> A
def test__cycle_selfloop_update(holder):
    sql = f"""
    {create_letter_table}

    UPDATE letter p
    SET a = a;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['column[letter.a]', 'column[letter.a]']]
    assert len(h.nodes) == 1
    assert len(h.edges) == 1


# test: A -> A
def test__cycle_selfloop(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (a)
    SELECT a FROM letter;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['column[letter.a]', 'column[letter.a]']]
    assert len(h.nodes) == 1
    assert len(h.edges) == 1


# test: A -> UPPER() -> A
def test__cycle_selfloop_via_one_function(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (a)
    SELECT UPPER(a) FROM letter;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['column[letter.a]', 'function[UPPER]', 'column[letter.a]']]
    assert len(h.nodes) == 2
    assert len(h.edges) == 2


def test__cycle_selfloop_via_three_functions(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (a)
    SELECT MD5(LOWER(UPPER(a))) FROM letter;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['column[letter.a]', 'function[UPPER]', 'function[LOWER]', 'function[MD5]', 'column[letter.a]']]
    assert len(h.nodes) == 4
    assert len(h.edges) == 4


# test: A -> UPPER() -> A, A -> LOWER() -> A
def test__cycle_two_selfloops_via_different_functions(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (a)
    SELECT UPPER(a) FROM letter;

    INSERT INTO letter (a)
    SELECT LOWER(a) FROM letter;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.a]', 'function[LOWER]', 'column[letter.a]'],
        ['column[letter.a]', 'function[UPPER]', 'column[letter.a]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 4


# test: A -> B, B -> A
def test__cycle_one_loop_two_columns(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = f"""
        {create_letter_table}

        INSERT INTO letter (b)
        SELECT a FROM letter;

        INSERT INTO letter (a)
        SELECT b FROM letter;
        """
        h = holder(sql=sql, dialect=DIALECT)

        assert h.paths == [['column[letter.a]', 'column[letter.b]', 'column[letter.a]']]
        assert len(h.nodes) == 2
        assert len(h.edges) == 2

    assert e.value.args[0] == "Found 1 errors with cycles in graph. Remove these."


# test: A -> B, B -> C, C -> A
def test__cycle_one_loop_three_columns(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = f"""
        {create_letter_table}

        INSERT INTO letter (b)
        SELECT a from LETTER;

        INSERT INTO letter (c)
        SELECT b from LETTER;

        INSERT INTO letter (a)
        SELECT c from LETTER;
        """
        h = holder(sql=sql, dialect=DIALECT)

        assert h.paths == [['column[letter.a]', 'column[letter.b]', 'column[letter.c]', 'column[letter.a]']]
        assert len(h.nodes) == 3
        assert len(h.edges) == 3

    assert e.value.args[0] == "Found 1 errors with cycles in graph. Remove these."


# test: A -> B, B -> A, A -> C, C -> A
## A joins the two loops
def test__cycle_two_loops(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = f"""
        {create_letter_table}

        INSERT INTO letter (b)
        SELECT a from LETTER;

        INSERT INTO letter (a)
        SELECT b from LETTER;

        INSERT INTO letter (c)
        SELECT a from LETTER;

        INSERT INTO letter (a)
        SELECT c from LETTER;
        """
        h = holder(sql=sql, dialect=DIALECT)

        assert h.paths == [
            ['column[letter.a]', 'column[letter.b]', 'column[letter.a]'],
            ['column[letter.a]', 'column[letter.c]', 'column[letter.a]'],
        ]
        assert len(h.nodes) == 3
        assert len(h.edges) == 4

    assert e.value.args[0] == "Found 2 errors with cycles in graph. Remove these."


# test: A -> B, B -> A, B -> C, C -> B
## B joins the two loops
def test__cycle_two_loops_modified(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = f"""
        {create_letter_table}

        INSERT INTO letter (b)
        SELECT a from LETTER;

        INSERT INTO letter (a)
        SELECT b from LETTER;

        INSERT INTO letter (c)
        SELECT b from LETTER;

        INSERT INTO letter (b)
        SELECT c from LETTER;
        """
        h = holder(sql=sql, dialect=DIALECT)

        assert h.paths == [
            ['column[letter.a]', 'column[letter.b]', 'column[letter.a]'],
            ['column[letter.b]', 'column[letter.c]', 'column[letter.b]']
        ]
        assert len(h.nodes) == 3
        assert len(h.edges) == 4

    assert e.value.args[0] == "Found 2 errors with cycles in graph. Remove these."


## Two disjoint cycles
# test: A -> B, B -> A, C -> D, D -> C
def test__cycle_two_loops_disjoint(holder):
    with pytest.raises(SqlLeafException) as e:
        sql = f"""
        {create_letter_table}

        INSERT INTO letter (b)
        SELECT a from LETTER;

        INSERT INTO letter (a)
        SELECT b from LETTER;

        INSERT INTO letter (d)
        SELECT c from LETTER;

        INSERT INTO letter (c)
        SELECT d from LETTER;
        """
        h = holder(sql=sql, dialect=DIALECT)

        assert h.paths == [
            ['column[letter.a]', 'column[letter.b]', 'column[letter.a]'],
            ['column[letter.c]', 'column[letter.d]', 'column[letter.c]']
        ]
        assert len(h.nodes) == 4
        assert len(h.edges) == 4

    assert e.value.args[0] == "Found 2 errors with cycles in graph. Remove these."


## No entry, One exit
# test: A -> A, A -> B, B -> C
def test__cycle_one_selfloop_at_start(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (b)
    SELECT a from LETTER;

    INSERT INTO letter (c)
    SELECT b from LETTER;

    -- Selfloops
    INSERT INTO letter (a)
    SELECT a from LETTER;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.a]', 'column[letter.a]'],
        ['column[letter.a]', 'column[letter.b]', 'column[letter.c]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 3


## No entry, One exit
# test: C -> B, B -> A, C -> C
def test__cycle_one_selfloop_at_start_reversed(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (b)
    SELECT c from LETTER;

    INSERT INTO letter (a)
    SELECT b from LETTER;

    -- Selfloops
    INSERT INTO letter (c)
    SELECT c from LETTER;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.c]', 'column[letter.c]'],
        ['column[letter.c]', 'column[letter.b]', 'column[letter.a]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 3


## One entry, One exit
# test: A -> B, B -> B, B -> C
def test__cycle_one_selfloop_at_middle(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (b)
    SELECT a from LETTER;

    INSERT INTO letter (c)
    SELECT b from LETTER;

    -- Selfloops
    INSERT INTO letter (b)
    SELECT b from LETTER;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.b]', 'column[letter.b]'],
        ['column[letter.a]', 'column[letter.b]', 'column[letter.c]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 3


## One entry, No exit
# test: A -> B, B -> C, C -> C
def test__cycle_one_selfloop_at_end(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (b)
    SELECT a from LETTER;

    INSERT INTO letter (c)
    SELECT b from LETTER;

    -- Selfloops
    INSERT INTO letter (c)
    SELECT c from LETTER;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.c]', 'column[letter.c]'],
        ['column[letter.a]', 'column[letter.b]', 'column[letter.c]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 3


# test: A -> B -> C, A -> A, B -> B, C -> C
def test__cycle_selfloop_at_each_node(holder):
    sql = f"""
    {create_letter_table}

    INSERT INTO letter (b)
    SELECT a from LETTER;

    INSERT INTO letter (c)
    SELECT b from LETTER;

    -- Selfloops
    INSERT INTO letter (a)
    SELECT a from LETTER;

    INSERT INTO letter (b)
    SELECT b from LETTER;

    INSERT INTO letter (c)
    SELECT c from LETTER;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[letter.a]', 'column[letter.a]'],
        ['column[letter.b]', 'column[letter.b]'],
        ['column[letter.c]', 'column[letter.c]'],
        ['column[letter.a]', 'column[letter.b]', 'column[letter.c]']
    ]
    assert len(h.nodes) == 3
    assert len(h.edges) == 5
