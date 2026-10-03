import os
import sys

from sqlleaf.models.query import InsertQuery, QueryHolder, PerformQuery, ExecuteDynamicQuery, SelectQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "plpgsql"

# TODO: variables should be included in the lineage graph too

def test_call_procedure_in_out_params(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_name varchar := $1;
            my_age integer := 1;
        BEGIN
            INSERT INTO target (name, age) SELECT my_name, my_age;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = call_downstream.downstream_holders[2].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'hello' AS name, 1 AS age"
    )
    assert h.paths == [['literal["hello"]', "column[target.name]"], ["literal[1]", "column[target.age]"]]


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
        ["literal[2]", "column[target.age]"]
    ]


def test_call_procedure_cursor(holder):
    sql = """
    CREATE TABLE source (name TEXT, age INTEGER);
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE OR REPLACE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            src RECORD;
        BEGIN
            FOR src IN SELECT * FROM source LOOP
                INSERT INTO target (name) SELECT src.name;
            END LOOP;
        END;
    $$;

    CALL hello('hello');
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[3].downstream_holders[0].downstream_holders[1].downstream_holders[1].transformed
    # TODO: this a bug - only one column should be returned in the subquery
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT (SELECT source.name AS name, source.age AS age FROM source AS source).name AS name"
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

    perform_query = h.holders[3].downstream_holders[0].downstream_holders[0].parent_holder.downstream_holders[0].transformed
    assert isinstance(perform_query, PerformQuery)
    assert perform_query.statement.sql(dialect=DIALECT) == "PERFORM (SELECT 5 AS _col_0) AS _col_0"
    assert h.paths == []


def test_nested_block_variable_shadowing(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

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
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['literal["inner"]', "column[target.name]"],
        ["literal[2]", "column[target.age]"],
        ['literal["outer"]', "column[target.name]"],
        ["literal[1]", "column[target.age]"],
    ]

def test_execute_dynamic(holder):
    sql = """
    CREATE TABLE target (name VARCHAR);

    CREATE PROCEDURE hello(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
        DECLARE
            my_name varchar := $1;
        BEGIN
            EXECUTE 'INSERT INTO target (name) SELECT $1' USING my_name;
        END;
    $$;

    CALL hello('there');
    """

    h = holder(sql=sql, dialect=DIALECT)

    call_downstream: QueryHolder = h.holders[2].downstream_holders[0]
    execute_holder: QueryHolder = call_downstream.downstream_holders[1]
    assert isinstance(execute_holder.original, ExecuteDynamicQuery)
    insert_query: InsertQuery = execute_holder.downstream_holders[0].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'there' AS name"
    assert h.paths == [['literal["there"]', "column[target.name]"]]
