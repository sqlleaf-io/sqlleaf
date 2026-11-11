import os
import sys

import pytest

from sqlleaf import exception
from sqlleaf.models.query import CTASQuery, TableQuery
from tests.new_fixtures import holder as holder, to_sql as to_sql

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__ctas(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (FORMAT = 'Parquet')
    AS SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)
    statements = [h.holders[1].transformed.statement]
    assert to_sql(statements, dialect=DIALECT) == ["CREATE TABLE awsdatacatalog.target WITH (format='Parquet') AS SELECT source.name AS name FROM awsdatacatalog.source AS source"]

    assert h.paths == [["column[awsdatacatalog.source.name]", "column[awsdatacatalog.target.name]"]]


def test__ctas_external_location_valid(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (
      external_location = 's3://amzn-s3-demo-bucket/my_orc_stas_table/',
      format = 'ORC'
    )
    AS SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery, CTASQuery]


def test__ctas_iceberg_valid(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (
      table_type = 'ICEBERG',
      format = 'PARQUET',
      location = 's3://amzn-s3-demo-bucket/ctas_iceberg_parquet/',
      is_external = false,
      partitioning = ARRAY['month(dt)'],
      vacuum_min_snapshots_to_keep = 10,
      vacuum_max_snapshot_age_seconds = 604800
    )
    AS SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.collected_queries.unsupported) == 0
    assert h.query_types == [TableQuery, CTASQuery]


def test__ctas_iceberg_external_location_fails(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (
      table_type = 'ICEBERG',
      external_location = 's3://amzn-s3-demo-bucket/ctas_iceberg_parquet/',
      is_external = false
    )
    AS SELECT * FROM source;
    """
    with pytest.raises(exception.InvalidQueryError, match="'external_location' is not supported for ICEBERG tables"):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_iceberg_is_external_true_fails(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (
      table_type = 'ICEBERG',
      location = 's3://amzn-s3-demo-bucket/ctas_iceberg_parquet/',
      is_external = true
    )
    AS SELECT * FROM source;
    """
    with pytest.raises(exception.InvalidQueryError, match="'is_external' must be false for ICEBERG tables"):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_iceberg_without_location_fails(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE TABLE target
    WITH (
      table_type = 'ICEBERG',
      format = 'PARQUET',
      is_external = false
    )
    AS SELECT * FROM source;
    """
    with pytest.raises(exception.InvalidQueryError, match="'location' is required for ICEBERG CTAS tables"):
        holder(sql=sql, dialect=DIALECT)


def test__ctas_iceberg_with_external_keyword_fails(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);

    CREATE EXTERNAL TABLE target
    WITH (
      table_type = 'ICEBERG',
      location = 's3://amzn-s3-demo-bucket/ctas_iceberg_parquet/',
      is_external = false
    )
    AS SELECT * FROM source;
    """
    with pytest.raises(exception.InvalidQueryError, match="'EXTERNAL' is not supported for ICEBERG tables"):
        holder(sql=sql, dialect=DIALECT)
