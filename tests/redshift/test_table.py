import os
import sys

from sqlleaf.objects.query_types import TableQuery
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
    assert "column[name type=UNKNOWN kind=file format=TEXTFILE path=s3://my-bucket/new/fruit/]" in h.nodes_full
    assert "column[name=age table=ext schema=fruit type=INT kind=table subkind=external]" in h.nodes_full
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__table_temporary(holder):
    sql = """
    CREATE TABLE #banana (name VARCHAR);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert [TableQuery] == list(map(type, h.queries))
    assert h.queries[0].property == "temporary"


def test__ctas_temporary(holder):
    sql = """
    CREATE TABLE #banana AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[#banana.name]"],
        ["column[fruit.raw.age]", "column[#banana.age]"],
    ]
    assert "column[name=age table=#banana type=INT kind=table subkind=temporary]" in h.nodes_full
    assert "column[name=name table=#banana type=VARCHAR kind=table subkind=temporary]" in h.nodes_full

    assert len(h.nodes) == 4
    assert len(h.edges) == 2


"""
create table eventdistsort1
distkey (eventid)
sortkey (eventid, dateid)
as
select eventid, venueid, dateid, eventname
from event;
"""
