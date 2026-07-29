import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__table_external(holder):
    sql = """
    CREATE EXTERNAL TABLE fruit.ext (
        name VARCHAR,
        age INT
    )
    ROW FORMAT DELIMITED
    FIELDS TERMINATED BY '\t'
    STORED AS TEXTFILE
    LOCATION 's3://my-bucket/new/fruit/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[name path=s3://my-bucket/new/fruit/]", "column[fruit.ext.name]"],
        ["column[age path=s3://my-bucket/new/fruit/]", "column[fruit.ext.age]"],
    ]
    assert h.nodes_full == [
         'column[name=age type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://my-bucket/new/fruit/]]',
         'column[name=name type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://my-bucket/new/fruit/]]',
         'column[name=age type=INT properties=[kind=table subkind=external table=ext schema=fruit]]',
         'column[name=name type=VARCHAR properties=[kind=table subkind=external table=ext schema=fruit]]',
     ]

    assert len(h.nodes) == 4
    assert len(h.edges) == 2
