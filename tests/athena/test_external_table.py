import os
import sys

from sqlleaf.models.query import TableQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__external_table(holder):
    sql = """
    CREATE EXTERNAL TABLE my_table (age INT, name STRING)
    STORED AS TEXTFILE
    LOCATION 's3://bucket/path/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[age path=s3://bucket/path/]", "column[my_table.age]"],
        ["column[name path=s3://bucket/path/]", "column[my_table.name]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://bucket/path/]]",
        "column[name=name type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://bucket/path/]]",
        "column[name=age type=INT properties=[kind=table subkind=external table=my_table]]",
        "column[name=name type=TEXT properties=[kind=table subkind=external table=my_table]]",
    ]
    assert len(h.edges) == 2
    assert h.query_types == [TableQuery]
