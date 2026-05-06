import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import holder
from sqlleaf.objects.query_types import ProcedureQuery

DIALECT = "postgres"


def test__procedure_simple(holder):
    sql = """
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
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.kind]", "function[UPPER()]", "column[cte.knd]", "function[LOWER()]", "column[fruit.processed.kind]"],
        ["variable[v_amount]", "column[fruit.processed.amount]"],
        ["literal[1]", "column[fruit.processed.number]"],
    ]
    assert len(h.queries) == 1 and isinstance(h.queries[0], ProcedureQuery)


# TODO: test an SP with a merge. This creates a 3-level query hierarchy
