import os
import sys

from sqlleaf.models.query import BlockQuery, ExecuteDynamicQuery, FetchQuery, InsertQuery, LoopQuery, OpenQuery, PerformQuery, QueryHolder
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
    assert perform_query.statement.sql(dialect=DIALECT) == "PERFORM (SELECT 5 AS _col_0) AS _col_0"
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
    open_query: OpenQuery = block_holder.downstream_holders[1].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('abc') AS name"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[2]
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
    open_query: OpenQuery = block_holder.downstream_holders[3].transformed
    assert (
        open_query.statement.sql(dialect=DIALECT)
        == "OPEN curs FOR SELECT UPPER('abc') AS name"
    )

    loop_holder: QueryHolder = block_holder.downstream_holders[4]
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
    open_query: OpenQuery = block_holder.downstream_holders[3].transformed
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
    open_query: OpenQuery = block_holder.downstream_holders[6].transformed
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

# TODO:
#  Test variable scoping (FOR loop has its vars popped)
#  'INTO' ...
#  FOREACH
#  EXCEPTION WHEN .. THEN ..

# EXECUTE 'CREATE TABLE test1 (id int);
#              INSERT INTO test1 VALUES (1);
#              CREATE TABLE test2 (id int);';
