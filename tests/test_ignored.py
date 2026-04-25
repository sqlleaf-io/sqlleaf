import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import holder
from sqlleaf.objects.query_types import InsertQuery, UpdateQuery

DIALECT = "postgres"


def test__ignore_transaction_statements(holder):
    queries = """
    BEGIN;
    COMMIT;
    ROLLBACK;
    END;
    START TRANSACTION;
    END TRANSACTION;
    ROLLBACK TO 'hello';
    --SAVEPOINT 'hello';    -- Not recognised by sqlglot
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_friendly_node_names()
    queries = h.get_queries_created()

    assert len(nodes) == 0
    assert len(queries) == 0
