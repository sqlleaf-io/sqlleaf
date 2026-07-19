import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__database(holder):
    sql = """
    CREATE DATABASE food;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []


def test__database_s3(holder):
    sql = """
    CREATE DATABASE food
    LOCATION 's3://amzn-s3-demo-bucket/food/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
