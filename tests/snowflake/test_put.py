import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import PutQuery, StageQuery

DIALECT = "snowflake"


def test___put_stage(holder):
    sql = """
    CREATE STAGE my_int_stage
    URL='s3://load/files/';

    PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [StageQuery, PutQuery] == list(map(type, h.queries))
    assert h.paths == [["column[? path=/tmp/data/mydata.csv]", "column[? stage=MY_INT_STAGE]"]]
