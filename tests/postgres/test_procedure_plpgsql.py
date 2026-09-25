import os
import sys

from sqlleaf.models.query import InsertQuery, QueryHolder
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
