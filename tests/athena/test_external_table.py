import os
import sys

import pytest

from sqlleaf import exception
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
        ["column[age path=s3://bucket/path/]", "column[awsdatacatalog.my_table.age]"],
        ["column[name path=s3://bucket/path/]", "column[awsdatacatalog.my_table.name]"],
    ]
    assert h.nodes_full == [
        "column[name=age type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://bucket/path/]]",
        "column[name=name type=UNKNOWN properties=[kind=file format=TEXTFILE path=s3://bucket/path/]]",
        "column[name=age type=INT properties=[kind=table subkind=external table=my_table schema=awsdatacatalog]]",
        "column[name=name type=TEXT properties=[kind=table subkind=external table=my_table schema=awsdatacatalog]]",
    ]
    assert len(h.edges) == 2
    assert h.query_types == [TableQuery]


def test__external_table_with_location_and_format_valid(holder):
    sql = """
    CREATE EXTERNAL TABLE my_table (age INT, name STRING)
    STORED AS PARQUET
    LOCATION 's3://bucket/path/'
    TBLPROPERTIES ('classification' = 'parquet');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery]


def test__external_table_iceberg_fails(holder):
    with pytest.raises(exception.InvalidQueryError, match="'EXTERNAL' is not supported for ICEBERG tables"):
        sql = """
        CREATE EXTERNAL TABLE iceberg_table (id bigint, data string)
        LOCATION 's3://bucket/path/'
        TBLPROPERTIES ('table_type' = 'ICEBERG');
        """
        holder(sql=sql, dialect=DIALECT)


def test__iceberg_table_with_location_valid(holder):
    sql = """
    CREATE TABLE iceberg_table (id bigint, data string)
    LOCATION 's3://bucket/path/'
    TBLPROPERTIES ('table_type' = 'ICEBERG');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery]


def test__iceberg_table_without_location_valid(holder):
    sql = """
    CREATE TABLE iceberg_table (id bigint, data string)
    TBLPROPERTIES ('table_type' = 'ICEBERG');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery]


def test__iceberg_table_without_external_keyword_valid(holder):
    sql = """
    CREATE TABLE iceberg_table (id bigint, data string)
    LOCATION 's3://bucket/path/'
    TBLPROPERTIES ('table_type' = 'ICEBERG', 'format' = 'parquet');
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery]
