import os
import sys

from sqlleaf.models.query import BlockQuery, DoQuery, InsertQuery, QueryHolder
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "plpgsql"


def test_do_simple(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    DO $$
    BEGIN
        INSERT INTO target (name, age) VALUES ('bob', 25);
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["bob"]', "column[target.name]"],
        ["literal[25]", "column[target.age]"],
    ]


def test_do_variable_assignment(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    DO $$
    DECLARE
        my_name varchar := 'there';
        my_age integer := 1;
    BEGIN
        my_age := 2;
        INSERT INTO target (name, age) SELECT my_name, my_age;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    do_query = h.holders[1].original
    assert isinstance(do_query, DoQuery)
    assert do_query.language == "PLPGSQL"

    block_holder: QueryHolder = h.holders[1].downstream_holders[0]
    assert isinstance(block_holder.original, BlockQuery)

    insert_query: InsertQuery = block_holder.downstream_holders[3].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name, age) SELECT 'there' AS name, 2 AS age"
    )
    assert h.paths == [
        ['literal["there"]', "column[target.name]"],
        ["literal[2]", "column[target.age]"],
    ]
