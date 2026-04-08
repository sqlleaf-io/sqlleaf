import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlleaf import structs
from tests.new_fixtures import (
    holder
)

DIALECT = 'postgres'

def test__procedure_simple(holder):
    queries = '''
    CREATE OR REPLACE PROCEDURE fruit.process(v_kind VARCHAR, v_amount INT)
    LANGUAGE plpgsql
    SECURITY DEFINER
    AS $$

    DECLARE
        v_name VARCHAR;

        BEGIN

        WITH cte AS (
            SELECT upper(kind) AS knd
            FROM fruit.raw
        )
        INSERT INTO fruit.processed (amount, number, kind)
        SELECT v_amount     as amount,
               1            as number,
               lower(c.knd) as kind
        FROM cte c;

        EXCEPTION WHEN OTHERS THEN
        SELECT 1;
        END;
    $$;
    '''
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert len(queries) == 1 and isinstance(queries[0], structs.ProcedureQuery)
    assert paths == [
        ['column[fruit.raw.kind]', 'function[UPPER()]', 'column[cte.knd]', 'function[LOWER()]', 'column[fruit.processed.kind]'],
        ['variable[v_amount]', 'column[fruit.processed.amount]'],
        ['literal[1]', 'column[fruit.processed.number]']
    ]

# TODO: test an SP with a merge. This creates a 3-level query hierarchy
