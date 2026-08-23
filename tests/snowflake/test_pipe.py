import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test__pipe(holder):
    sql = """
    CREATE PIPE mypipe
    AS
    COPY INTO mytable
    FROM @mystage
    FILE_FORMAT = (TYPE = 'JSON');

    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
