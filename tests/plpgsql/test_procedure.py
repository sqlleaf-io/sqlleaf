import os
import sys

import pytest
import sqlglot

from sqlleaf import exception
from sqlleaf.models.query import BlockQuery, CaseQuery, ExceptionQuery, ExecuteDynamicQuery, FetchQuery, IfQuery, InsertQuery, LoopQuery, OpenQuery, PerformQuery, QueryHolder
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "plpgsql"

# TODO: variables should be included in the lineage graph too


def test_procedure_variable_assignment(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_name varchar := $1;
            my_age integer := 1;
        BEGIN
            my_age := 2;
            my_name := 'there';
            INSERT INTO target (name, age) SELECT my_name, my_age;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = call_downstream.downstream_holders[4].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'there' AS name, 2 AS age"
    )
    assert h.paths == [
        ['literal["there"]', "column[target.name]"],
        ["literal[2]", "column[target.age]"],
    ]


def test_procedure_variable_assignment_more(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_name ALIAS FOR $1;
            my_age integer DEFAULT 32;
        BEGIN
            my_age := 2;
            my_name := 'there';
            INSERT INTO target (name, age) SELECT my_name, my_age;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = call_downstream.downstream_holders[4].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'there' AS name, 2 AS age"
    )
    assert h.paths == [
        ['literal["there"]', "column[target.name]"],
        ["literal[2]", "column[target.age]"],
    ]



def test_procedure_for_in_select(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            src RECORD;
        BEGIN
            FOR src IN SELECT * FROM source LOOP -- TODO: InsertQuery with Source=SELECT, Target=VARIABLE[src]
                INSERT INTO target (name) SELECT src.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[3].downstream_holders[0].downstream_holders[1].downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]


def test_procedure_perform_simple_select(holder):
    sql = """
    CREATE FUNCTION my_adder(a int, b int)
    RETURNS INTEGER
    RETURN a + b;

    CREATE TABLE t (a INT, b INT);

    CREATE PROCEDURE hello()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        PERFORM my_adder(2, 3);
    END;
    $$;

    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    perform_query = (
        h.holders[3].downstream_holders[0].downstream_holders[0].parent_holder.downstream_holders[0].transformed
    )
    assert isinstance(perform_query, PerformQuery)
    assert perform_query.statement.sql(dialect=DIALECT) == "PERFORM (SELECT 5 AS _col_0) AS my_adder"
    assert h.paths == []


def test_procedure_nested_block_variable_shadowing(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        BEGIN
            DECLARE
                my_age integer := 1;
            BEGIN
                BEGIN
                    DECLARE
                        my_age integer := 2;
                    BEGIN
                        INSERT INTO target (name, age) SELECT 'inner', my_age;
                    END;
                END;
                INSERT INTO target (name, age) SELECT 'outer', my_age;
            END;
        END;
    $$;

    CALL hello('there');
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_holder: QueryHolder = h.holders[2]
    block_1_holder: QueryHolder = call_holder.downstream_holders[0]
    block_2_holder: QueryHolder = block_1_holder.downstream_holders[0]
    block_2_insert: InsertQuery = block_2_holder.downstream_holders[2].transformed
    block_3_holder: QueryHolder = block_2_holder.downstream_holders[1]
    block_4_holder: QueryHolder = block_3_holder.downstream_holders[0]
    block_4_insert: InsertQuery = block_4_holder.downstream_holders[1].transformed

    assert block_2_insert.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'outer' AS name, 1 AS age"
    assert block_4_insert.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'inner' AS name, 2 AS age"

    assert h.paths == [
        ['literal["inner"]', "column[target.name]"],
        ["literal[2]", "column[target.age]"],
        ['literal["outer"]', "column[target.name]"],
        ["literal[1]", "column[target.age]"],
    ]


def test_procedure_execute_dynamic_using(holder):
    sql = """
    CREATE TABLE target (name VARCHAR);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_name varchar := $1;
        BEGIN
            EXECUTE 'INSERT INTO target (name) SELECT $1' USING UPPER(my_name);
        END;
    $$;

    CALL hello('there');
    """

    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    execute_holder: QueryHolder = call_downstream.downstream_holders[1]
    assert isinstance(execute_holder.original, ExecuteDynamicQuery)
    insert_query: InsertQuery = execute_holder.downstream_holders[0].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT UPPER('there') AS name"
    assert h.paths == [['literal["there"]', "function[UPPER]", "column[target.name]"]]


def test_procedure_execute_dynamic_variable(holder):
    sql = """
    CREATE TABLE target (age INT);

    CREATE PROCEDURE hello(num INT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_query varchar := 'INSERT INTO target (age) SELECT $1';
        BEGIN
            EXECUTE my_query USING $1;
        END;
    $$;

    CALL hello(4);
    """

    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    execute_holder: QueryHolder = call_downstream.downstream_holders[1]
    assert isinstance(execute_holder.original, ExecuteDynamicQuery)
    insert_query: InsertQuery = execute_holder.downstream_holders[0].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (age) SELECT 4 AS age"
    assert h.paths == [["literal[4]", "column[target.age]"]]


def test_execute_dynamic_concat(holder):
    sql = """
    CREATE TABLE target (name VARCHAR);

    CREATE PROCEDURE hello(name VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
        BEGIN
            EXECUTE 'INSERT INTO target (name) SELECT * FROM ' || $1;
        END;
    $$;

    CALL hello('target');
    """

    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    execute_holder: QueryHolder = call_downstream.downstream_holders[0]
    assert isinstance(execute_holder.original, ExecuteDynamicQuery)
    insert_query: InsertQuery = execute_holder.downstream_holders[0].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT target.name AS name FROM target AS target"
    )
    assert h.paths == [["column[target.name]", "column[target.name]"]]


def test_execute_dynamic_quote_ident(holder):
    sql = """
    CREATE TABLE target (name VARCHAR);

    CREATE PROCEDURE hello()
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            tabname varchar := 'target';
        BEGIN
            EXECUTE 'INSERT INTO ' || QUOTE_IDENT(tabname) || ' SELECT 1;';
        END;
    $$;

    CALL hello();
    """

    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    execute_holder: QueryHolder = call_downstream.downstream_holders[1]
    assert isinstance(execute_holder.original, ExecuteDynamicQuery)
    select_query = execute_holder.downstream_holders[0].transformed
    assert select_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 1 AS name"
    assert h.paths == [["literal[1]", "column[target.name]"]]


def test_procedure_for_in_execute(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            src RECORD;
        BEGIN
            FOR src IN EXECUTE 'SELECT * FROM source' LOOP
                INSERT INTO target (name) SELECT src.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[3].downstream_holders[0].downstream_holders[1].downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]


def test_procedure_open_cursor_bound(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            r_name RECORD;
            curs CURSOR FOR SELECT * FROM source;
        BEGIN
            OPEN curs;
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: BlockQuery = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[2].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT source.name AS name, source.age AS age FROM source AS source"
    )

    insert_query: InsertQuery = block_holder.downstream_holders[3].downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]


def test_procedure_open_cursor_unbound(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            r_name RECORD;
            curs refcursor;
        BEGIN
            OPEN curs FOR SELECT * FROM source; -- TODO: InsertQuery with Source=SELECT, Target=VARIABLE[curs]
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name; 
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[2].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT source.name AS name, source.age AS age FROM source AS source"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[3]
    insert_query: InsertQuery = loop_holder.downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]

def test_procedure_open_cursor_execute(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            r_name RECORD;
            curs refcursor;
        BEGIN
            OPEN curs FOR EXECUTE 'SELECT * FROM source';
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[2].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT source.name AS name, source.age AS age FROM source AS source"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[3]
    insert_query: InsertQuery = loop_holder.downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]


def test_procedure_open_cursor_bound_parameters(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            r_name RECORD;
            curs CURSOR (key VARCHAR) FOR SELECT UPPER(key) as name;
        BEGIN
            OPEN curs('abc');
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[2].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('abc') AS name"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[3]
    insert_query: InsertQuery = loop_holder.downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT UPPER('abc') AS name).name AS name"
    )
    assert h.paths == [['literal["abc"]', "function[UPPER]", "column[target.name]"]]


def test_procedure_open_cursor_bound_parameters_with_variable(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            key varchar;
            r_name RECORD;
            curs CURSOR (key VARCHAR) FOR SELECT UPPER(key) as name;
        BEGIN
            key := 'abc';
            OPEN curs;
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[4].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('abc') AS name"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[5]
    insert_query: InsertQuery = loop_holder.downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT (SELECT UPPER('abc') AS name).name AS name"
    )
    assert h.paths == [['literal["abc"]', "function[UPPER]", "column[target.name]"]]


def test_procedure_open_cursor_bound_parameters_precedence(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            key varchar;
            r_name RECORD;
            curs CURSOR (key VARCHAR) FOR SELECT UPPER(key) as name;
        BEGIN
            key := 'from_var';
            OPEN curs('explicit');
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[4].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('explicit') AS name"
    )
    assert h.paths == [['literal["explicit"]', "function[UPPER]", "column[target.name]"]]


def test_procedure_open_cursor_bound_parameters_multiple_and_unrelated_variable(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            k1 varchar;
            k2 varchar;
            unrelated varchar;
            r_name RECORD;
            curs CURSOR (k1 VARCHAR, k2 VARCHAR) FOR SELECT UPPER(k1) as name, LOWER(k2) as other_name;
        BEGIN
            k1 := 'abc';
            unrelated := 'xyz';
            OPEN curs(k2 => 'def');
            LOOP
                FETCH curs INTO r_name;
                INSERT INTO target (name) SELECT r_name.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    open_query: OpenQuery = block_holder.downstream_holders[7].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('abc') AS name, LOWER('def') AS other_name"
    )
    assert h.paths == [['literal["abc"]', "function[UPPER]", "column[target.name]"]]


def test_procedure_fetch_multiple_targets(holder):
    sql = """
    CREATE TABLE source (a INTEGER, b INTEGER, c INTEGER);
    CREATE TABLE target (a INTEGER, b INTEGER, c INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            foo INTEGER;
            bar INTEGER;
            baz INTEGER;
            curs2 CURSOR FOR SELECT * FROM source;
        BEGIN
            OPEN curs2;
            LOOP
                FETCH curs2 INTO foo, bar, baz;
                INSERT INTO target (a, b, c) SELECT foo, bar, baz;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    loop_holder: QueryHolder = block_holder.downstream_holders[5]
    insert_query: InsertQuery = loop_holder.downstream_holders[1].transformed

    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (a, b, c) SELECT (SELECT source.a AS a, source.b AS b, source.c AS c FROM source AS source).a AS a, (SELECT source.a AS a, source.b AS b, source.c AS c FROM source AS source).b AS b, (SELECT source.a AS a, source.b AS b, source.c AS c FROM source AS source).c AS c"
    assert h.paths == [
        ["column[source.a]", "column[target.a]"],
        ["column[source.b]", "column[target.b]"],
        ["column[source.c]", "column[target.c]"],
    ]


def test_procedure_if_elsif_else(holder):
    sql = """
    CREATE TABLE source_a (name TEXT);
    CREATE TABLE source_b (name TEXT);
    CREATE TABLE source_c (name TEXT);
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE hello(val INT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        IF val = 1 THEN
            INSERT INTO target (name) SELECT source_a.name FROM source_a;
        ELSIF val = 2 THEN
            INSERT INTO target (name) SELECT source_b.name FROM source_b;
        ELSE
            INSERT INTO target (name) SELECT source_c.name FROM source_c;
        END IF;
    END;
    $$;

    CALL hello(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_holder: QueryHolder = h.holders[5].downstream_holders[0]
    if_holder: QueryHolder = call_holder.downstream_holders[0]
    assert isinstance(if_holder.original, IfQuery)
    assert len(if_holder.downstream_holders) == 3

    assert h.paths == [
        ["column[source_a.name]", "column[target.name]"],
        ["column[source_b.name]", "column[target.name]"],
        ["column[source_c.name]", "column[target.name]"],
    ]


def test_procedure_if_condition_excluded_from_lineage(holder):
    sql = """
    CREATE TABLE source (name TEXT, condition_col TEXT);
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE hello()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        cond_var TEXT := 'check';
    BEGIN
        IF cond_var = 'check' THEN
            INSERT INTO target (name) SELECT source.name FROM source;
        END IF;
    END;
    $$;

    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[source.name]", "column[target.name]"],
    ]
    assert "column[source.condition_col]" not in h.nodes
    assert 'literal["check"]' not in h.nodes


def test_procedure_if_nested_in_loop(holder):
    sql = """
    CREATE TABLE source (name TEXT);
    CREATE TABLE target_a (name TEXT);
    CREATE TABLE target_b (name TEXT);

    CREATE OR REPLACE PROCEDURE hello()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        curs CURSOR FOR SELECT * FROM source;
        r RECORD;
    BEGIN
        OPEN curs;
        LOOP
            FETCH curs INTO r;
            IF r.name IS NOT NULL THEN
                INSERT INTO target_a (name) SELECT r.name;
            ELSE
                INSERT INTO target_b (name) SELECT 'unknown';
            END IF;
        END LOOP;
    END;
    $$;

    CALL hello();
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_holder: QueryHolder = h.holders[4].downstream_holders[0]
    loop_holder: QueryHolder = call_holder.downstream_holders[3]
    assert isinstance(loop_holder.original, LoopQuery)
    if_holder: QueryHolder = loop_holder.downstream_holders[1]
    assert isinstance(if_holder.original, IfQuery)
    assert len(if_holder.downstream_holders) == 2

    assert h.paths == [
        ["column[source.name]", "column[target_a.name]"],
        ['literal["unknown"]', "column[target_b.name]"],
    ]


# TODO: include only those statements that match the condition
def test_procedure_case_when_searched_branches(holder):
    sql = """
    CREATE TABLE source_a (name TEXT);
    CREATE TABLE source_b (name TEXT);
    CREATE TABLE source_c (name TEXT);
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE hello(val INT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        CASE
            WHEN val = 1 THEN
                INSERT INTO target (name) SELECT source_a.name FROM source_a;
            WHEN val = 2 THEN
                INSERT INTO target (name) SELECT source_b.name FROM source_b;
            ELSE
                INSERT INTO target (name) SELECT source_c.name FROM source_c;
        END CASE;
    END;
    $$;

    CALL hello(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_holder: QueryHolder = h.holders[5].downstream_holders[0]
    case_holder: QueryHolder = call_holder.downstream_holders[0]
    assert isinstance(case_holder.original, CaseQuery)
    assert len(case_holder.downstream_holders) == 3

    assert h.paths == [
        ["column[source_a.name]", "column[target.name]"],
        ["column[source_b.name]", "column[target.name]"],
        ["column[source_c.name]", "column[target.name]"],
    ]


# TODO: include only those statements that match the condition
def test_procedure_case_when_simple_without_else(holder):
    sql = """
    CREATE TABLE source_a (name TEXT);
    CREATE TABLE source_b (name TEXT);
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE hello(val INT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        CASE val
            WHEN 1 THEN
                INSERT INTO target (name) SELECT source_a.name FROM source_a;
            WHEN 2, 3 THEN
                INSERT INTO target (name) SELECT source_b.name FROM source_b;
        END CASE;
    END;
    $$;

    CALL hello(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_holder: QueryHolder = h.holders[4].downstream_holders[0]
    case_holder: QueryHolder = call_holder.downstream_holders[0]
    assert isinstance(case_holder.original, CaseQuery)
    assert len(case_holder.downstream_holders) == 2

    assert h.paths == [
        ["column[source_a.name]", "column[target.name]"],
        ["column[source_b.name]", "column[target.name]"],
    ]


# TODO: include only those statements that match the condition
def test_procedure_case_branch_variable_resolution(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE hello(val INT)
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        my_name varchar;
    BEGIN
        CASE val
            WHEN 1 THEN
                my_name := 'one';
                INSERT INTO target (name) SELECT my_name;
            ELSE
                my_name := 'other';
                INSERT INTO target (name) SELECT my_name;
        END CASE;
    END;
    $$;

    CALL hello(1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["one"]', "column[target.name]"],
        ['literal["other"]', "column[target.name]"],
    ]


"""
CREATE OR REPLACE FUNCTION get_simple_cursor(refcursor)
RETURNS refcursor AS $$
BEGIN
    -- $1 refers to the refcursor argument passed in. This creates a new variable (referenced by refcursor) with 'SELECT 1' as its assignment
    OPEN $1 FOR SELECT 1;

    RETURN $1;
END;
$$ LANGUAGE plpgsql;
"""
# And then pass the cursor to the SP:
"""
BEGIN;
-- 1. Call the function and assign a name ('my_cursor') to the cursor
SELECT get_simple_cursor('my_cursor');
-- 2. Fetch the data from the newly opened cursor
FETCH ALL IN my_cursor;
COMMIT;
"""


def test_procedure_exception_multiple_when(holder):
    sql = """
    CREATE TABLE source_a (name TEXT);
    CREATE TABLE source_b (name TEXT);
    CREATE TABLE source_c (name TEXT);
    CREATE TABLE target (name TEXT);

    CREATE OR REPLACE PROCEDURE test_multi_exception()
    LANGUAGE plpgsql
    AS $$
    BEGIN
        SELECT 1;
    EXCEPTION
        WHEN unique_violation THEN
            INSERT INTO target (name) SELECT source_a.name FROM source_a;
        WHEN division_by_zero THEN
            INSERT INTO target (name) SELECT source_b.name FROM source_b;
        WHEN OTHERS THEN
            INSERT INTO target (name) SELECT source_c.name FROM source_c;
    END;
    $$;

    CALL test_multi_exception();
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[5].downstream_holders[0]
    assert isinstance(block_holder.original, BlockQuery)
    exc_holder: QueryHolder = block_holder.downstream_holders[1]
    assert isinstance(exc_holder.original, ExceptionQuery)
    assert len(exc_holder.downstream_holders) == 3

    assert h.paths == [
        ["column[source_a.name]", "column[target.name]"],
        ["column[source_b.name]", "column[target.name]"],
        ["column[source_c.name]", "column[target.name]"],
    ]


def test_procedure_exception_nested_in_loop(holder):
    sql = """
    CREATE TABLE source (name TEXT);
    CREATE TABLE target_a (name TEXT);
    CREATE TABLE target_b (name TEXT);

    CREATE OR REPLACE PROCEDURE test_exception_nested()
    LANGUAGE plpgsql
    AS $$
    DECLARE
        curs CURSOR FOR SELECT * FROM source;
        r RECORD;
    BEGIN
        OPEN curs;
        LOOP
            FETCH curs INTO r;
            BEGIN
                INSERT INTO target_a (name) SELECT r.name;
            EXCEPTION
                WHEN OTHERS THEN
                    INSERT INTO target_b (name) SELECT 'fallback';
            END;
        END LOOP;
    END;
    $$;

    CALL test_exception_nested();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[target_a.name]"],
        ['literal["fallback"]', "column[target_b.name]"],
    ]


def test_procedure_variable_scope_multilevel_shadowing(holder):
    sql = """
    CREATE TABLE target (lvl TEXT, val TEXT);

    CREATE OR REPLACE PROCEDURE test_multilevel_scoping()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        a TEXT := 'L1_a';
    BEGIN
        DECLARE
            a TEXT := 'L2_a';
            b TEXT := 'L2_b';
        BEGIN
            DECLARE
                a TEXT := 'L3_a';
            BEGIN
                INSERT INTO target (lvl, val) SELECT 'L3', a || '_' || b;
            END;
            INSERT INTO target (lvl, val) SELECT 'L2', a || '_' || b;
        END;
        INSERT INTO target (lvl, val) SELECT 'L1', a;
    END;
    $$;

    CALL test_multilevel_scoping();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["L3"]', "column[target.lvl]"],
        ['literal["L3_a_L2_b"]', "column[target.val]"],
        ['literal["L2"]', "column[target.lvl]"],
        ['literal["L2_a_L2_b"]', "column[target.val]"],
        ['literal["L1"]', "column[target.lvl]"],
        ['literal["L1_a"]', "column[target.val]"],
    ]


def test_procedure_variable_scope_inner_var_out_of_scope_fails(holder):
    with pytest.raises(sqlglot.errors.OptimizeError) as e:
        sql = """
        CREATE TABLE target (val TEXT);

        CREATE OR REPLACE PROCEDURE test_inner_var_out_of_scope()
        LANGUAGE PLPGSQL
        AS $$
        BEGIN
            DECLARE
                inner_var TEXT := 'inner';
            BEGIN
                INSERT INTO target (val) SELECT inner_var;
            END;
            INSERT INTO target (val) SELECT inner_var;
        END;
        $$;

        CALL test_inner_var_out_of_scope();
        """
        h = holder(sql=sql, dialect=DIALECT)
    assert "Column 'inner_var' could not be resolved" in str(e.value)


def test_procedure_variable_scope_for_loop_isolation(holder):
    sql = """
    CREATE TABLE source (name TEXT);
    CREATE TABLE target_1 (val TEXT);
    CREATE TABLE target_2 (val TEXT);

    CREATE OR REPLACE PROCEDURE test_for_loop_isolation()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        src RECORD;
        val TEXT := 'outer_val';
    BEGIN
        FOR src IN SELECT name FROM source LOOP
            DECLARE
                val TEXT := 'loop_val';
            BEGIN
                INSERT INTO target_1 (val) SELECT val;
            END;
        END LOOP;
        INSERT INTO target_2 (val) SELECT val;
    END;
    $$;

    CALL test_for_loop_isolation();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["loop_val"]', "column[target_1.val]"],
        ['literal["outer_val"]', "column[target_2.val]"],
    ]


def test_procedure_variable_scope_inner_mutation_of_outer_var(holder):
    sql = """
    CREATE TABLE target (val TEXT);

    CREATE OR REPLACE PROCEDURE test_inner_mutation_of_outer_var()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        x TEXT := 'outer_init';
    BEGIN
        BEGIN
            x := 'inner_modified';
        END;
        INSERT INTO target (val) SELECT x;
    END;
    $$;

    CALL test_inner_mutation_of_outer_var();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["inner_modified"]', "column[target.val]"],
    ]


def test_procedure_variable_scope_loop_mutation_of_outer_var(holder):
    sql = """
    CREATE TABLE source (name TEXT);
    CREATE TABLE target (val TEXT);

    CREATE OR REPLACE PROCEDURE test_loop_mutation_of_outer_var()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        src RECORD;
        x TEXT := 'before_loop';
    BEGIN
        FOR src IN SELECT name FROM source LOOP
            x := 'during_loop';
        END LOOP;
        INSERT INTO target (val) SELECT x;
    END;
    $$;

    CALL test_loop_mutation_of_outer_var();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["during_loop"]', "column[target.val]"],
    ]


def test_procedure_variable_scope_for_range_loop_implicit_iterator(holder):
    sql = """
    CREATE TABLE target_1 (val INT);
    CREATE TABLE target_2 (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_scoping()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        i INT := 100;
    BEGIN
        FOR i IN 1..3 LOOP
            INSERT INTO target_1 (val) SELECT i;
        END LOOP;
        INSERT INTO target_2 (val) SELECT i;
    END;
    $$;

    CALL test_for_range_scoping();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[1]', "column[target_1.val]"],
        ['literal[2]', "column[target_1.val]"],
        ['literal[3]', "column[target_1.val]"],
        ['literal[100]', "column[target_2.val]"],
    ]


def test_procedure_variable_scope_nested_shadowing_and_mutation(holder):
    sql = """
    CREATE TABLE target_l2 (x TEXT, y TEXT);
    CREATE TABLE target_l1 (x TEXT, y TEXT);

    CREATE OR REPLACE PROCEDURE test_nested_shadowing_and_mutation()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        x TEXT := 'l1_x_init';
        y TEXT := 'l1_y_init';
    BEGIN
        DECLARE
            x TEXT := 'l2_x_shadow';
        BEGIN
            x := 'l2_x_modified';
            y := 'l1_y_modified';
            INSERT INTO target_l2 (x, y) SELECT x, y;
        END;
        INSERT INTO target_l1 (x, y) SELECT x, y;
    END;
    $$;

    CALL test_nested_shadowing_and_mutation();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["l2_x_modified"]', "column[target_l2.x]"],
        ['literal["l1_y_modified"]', "column[target_l1.y]"],
        ['literal["l1_y_modified"]', "column[target_l2.y]"],
        ['literal["l1_x_init"]', "column[target_l1.x]"],
    ]


def test_procedure_variable_scope_while_and_simple_loop_mutation(holder):
    sql = """
    CREATE TABLE target (val_while TEXT, val_loop TEXT);

    CREATE OR REPLACE PROCEDURE test_loop_mutations()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        w TEXT := 'before_while';
        l TEXT := 'before_loop';
    BEGIN
        WHILE TRUE LOOP
            w := 'in_while';
            EXIT;
        END LOOP;

        LOOP
            l := 'in_loop';
            EXIT;
        END LOOP;

        INSERT INTO target (val_while, val_loop) SELECT w, l;
    END;
    $$;

    CALL test_loop_mutations();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["in_while"]', "column[target.val_while]"],
        ['literal["in_loop"]', "column[target.val_loop]"],
    ]


def test_procedure_variable_scope_for_range_variable_bound(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_bound()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        start_val INT := 5;
        i INT := 999;
    BEGIN
        FOR i IN start_val..10 LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_bound();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[5]', "column[target.val]"],
        ['literal[6]', "column[target.val]"],
        ['literal[7]', "column[target.val]"],
        ['literal[8]', "column[target.val]"],
        ['literal[9]', "column[target.val]"],
        ['literal[10]', "column[target.val]"],
    ]


def test_procedure_variable_assignment_undeclared_fails(holder):
    sql = """
    CREATE OR REPLACE PROCEDURE test_undeclared_assignment()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        undeclared_var := 'val';
    END;
    $$;

    CALL test_undeclared_assignment();
    """
    with pytest.raises(exception.MappingError) as exc_info:
        holder(sql=sql, dialect=DIALECT)
    assert '"undeclared_var" is not a known variable' in str(exc_info.value)


def test_procedure_variable_assignment_nested_undeclared_fails(holder):
    sql = """
    CREATE OR REPLACE PROCEDURE test_nested_undeclared_assignment()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        x TEXT := 'init';
    BEGIN
        BEGIN
            y := 'val';
        END;
    END;
    $$;

    CALL test_nested_undeclared_assignment();
    """
    with pytest.raises(exception.MappingError) as exc_info:
        holder(sql=sql, dialect=DIALECT)
    assert '"y" is not a known variable' in str(exc_info.value)


def test_procedure_for_range_reverse(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_rev()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN REVERSE 3..1 LOOP
            RAISE NOTICE '%', i;
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_rev();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[3]', "column[target.val]"],
        ['literal[2]', "column[target.val]"],
        ['literal[1]', "column[target.val]"],
    ]


def test_procedure_for_range_by_step(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_step()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN 1..5 BY 2 LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_step();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[1]', "column[target.val]"],
        ['literal[3]', "column[target.val]"],
        ['literal[5]', "column[target.val]"],
    ]


def test_procedure_for_range_reverse_by_step(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_rev_step()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN REVERSE 5..1 BY 2 LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_rev_step();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[5]', "column[target.val]"],
        ['literal[3]', "column[target.val]"],
        ['literal[1]', "column[target.val]"],
    ]


def test_procedure_for_range_negative_bounds(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_neg()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN -3..-1 LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_neg();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[-3]', "column[target.val]"],
        ['literal[-2]', "column[target.val]"],
        ['literal[-1]', "column[target.val]"],
    ]


def test_procedure_for_range_empty(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_empty_proc()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN 3..1 LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_empty_proc();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []


def test_procedure_for_range_outer_var_mutation_across_iterations(holder):
    sql = """
    CREATE TABLE target (val INT, total INT);

    CREATE OR REPLACE PROCEDURE test_range_mutation()
    LANGUAGE PLPGSQL
    AS $$
    DECLARE
        accum INT := 0;
    BEGIN
        FOR i IN 1..3 LOOP
            accum := accum + 10;
            INSERT INTO target (val, total) SELECT i, accum;
        END LOOP;
    END;
    $$;

    CALL test_range_mutation();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[1]', "column[target.val]"],
        ['literal[10]', "column[target.total]"],
        ['literal[2]', "column[target.val]"],
        ['literal[20]', "column[target.total]"],
        ['literal[3]', "column[target.val]"],
        ['literal[30]', "column[target.total]"],
    ]


def test_procedure_for_range_expression_bounds(holder):
    sql = """
    CREATE TABLE target (val INT);

    CREATE OR REPLACE PROCEDURE test_for_range_expr_bounds()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        FOR i IN (1 + 1)..(2 * 3) BY (1 + 1) LOOP
            INSERT INTO target (val) SELECT i;
        END LOOP;
    END;
    $$;

    CALL test_for_range_expr_bounds();
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal[2]', "column[target.val]"],
        ['literal[4]', "column[target.val]"],
        ['literal[6]', "column[target.val]"],
    ]


# TODO:
#  Test variable scoping (FOR loop has its vars popped)
#  'INTO' ...
#  FOREACH

# EXECUTE 'CREATE TABLE test1 (id int);
#              INSERT INTO test1 VALUES (1);
#              CREATE TABLE test2 (id int);';
