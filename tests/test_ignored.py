import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import holder

DIALECT = "postgres"


def test__ignore_transaction_statements(holder):
    sql = """
    BEGIN;
    COMMIT;
    ROLLBACK;
    END;
    START TRANSACTION;
    END TRANSACTION;
    ROLLBACK TO 'hello';
    --SAVEPOINT 'hello';    -- Not recognised by sqlglot
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert len(h.nodes) == 0
    assert len(h.queries) == 0
