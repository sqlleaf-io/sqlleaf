import os
import sys

from sqlleaf.models.query import StageQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test___stage_internal(holder):
    sql = "CREATE STAGE my_int_stage;"
    h = holder(sql=sql, dialect=DIALECT)

    assert [StageQuery] == h.query_types
    stage_query = h.holders[0].original
    assert isinstance(stage_query, StageQuery)
    assert stage_query.name == "@MY_INT_STAGE"
    assert stage_query.path == ""


def test___stage_external_s3(holder):
    sql = "CREATE STAGE my_s3_stage URL = 's3://mybucket/data/' STORAGE_INTEGRATION = s3_int;"
    h = holder(sql=sql, dialect=DIALECT)

    assert [StageQuery] == h.query_types
    stage_query = h.holders[0].original
    assert isinstance(stage_query, StageQuery)
    assert stage_query.name == "@MY_S3_STAGE"
    assert stage_query.path == "s3://mybucket/data/"


def test___stage_temporary(holder):
    sql = "CREATE TEMPORARY STAGE my_temp_stage;"
    h = holder(sql=sql, dialect=DIALECT)

    assert [StageQuery] == h.query_types
    stage_query = h.holders[0].original
    assert isinstance(stage_query, StageQuery)
    assert stage_query.name == "@MY_TEMP_STAGE"
    assert stage_query.is_temporary
