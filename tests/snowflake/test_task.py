import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test__task(holder):
    sql = """
    CREATE TASK t1
    SCHEDULE = '60 MINUTES'
    TIMESTAMP_INPUT_FORMAT = 'YYYY-MM-DD HH24'
    USER_TASK_MANAGED_INITIAL_WAREHOUSE_SIZE = 'XSMALL'
    AS
    INSERT INTO mytable(ts) VALUES(CURRENT_TIMESTAMP);

    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
