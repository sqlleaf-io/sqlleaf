import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__schema(holder):
    sql = """
    CREATE SCHEMA food
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []


def test__schema_s3(holder):
    sql = """
    CREATE SCHEMA food
    LOCATION 's3://amzn-s3-demo-bucket/food/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
