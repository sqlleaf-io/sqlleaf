import os
import sys

from sqlleaf.models.query import CopyQuery, TableQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"

simple_table = "CREATE TABLE fruit.simple (name VARCHAR, age INT);"
iam_role = "IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole'"


def test_copy_s3_standard(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://bucket/path' {iam_role};
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=s3://bucket/path]", "column[fruit.simple.name]"],
        ["column[age path=s3://bucket/path]", "column[fruit.simple.age]"],
    ]


def test_copy_s3_column_list(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple (name) FROM 's3://bucket/path' {iam_role} CSV;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=s3://bucket/path]", "column[fruit.simple.name]"],
    ]


def test_copy_dynamodb(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 'dynamodb://MyDynamoTable' {iam_role} READRATIO 50;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=dynamodb://MyDynamoTable]", "column[fruit.simple.name]"],
        ["column[age path=dynamodb://MyDynamoTable]", "column[fruit.simple.age]"],
    ]


def test_copy_emr(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 'emr://j-12345678/output/path' {iam_role};
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=emr://j-12345678/output/path]", "column[fruit.simple.name]"],
        ["column[age path=emr://j-12345678/output/path]", "column[fruit.simple.age]"],
    ]


def test_copy_ssh(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://mybucket/ssh_manifest' {iam_role} SSH;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=s3://mybucket/ssh_manifest]", "column[fruit.simple.name]"],
        ["column[age path=s3://mybucket/ssh_manifest]", "column[fruit.simple.age]"],
    ]


def test_copy_temp_table(holder):
    sql = f"""
    CREATE TABLE "#fruit.simple" (name VARCHAR, age INT);
    COPY "#fruit.simple" FROM 's3://bucket/path' {iam_role};
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths ==  [
         ['column[name path=s3://bucket/path]', 'column[#fruit.simple.name]'],
         ['column[age path=s3://bucket/path]', 'column[#fruit.simple.age]']
     ]


# TODO: JSONPaths is extremely complex
#  https://docs.aws.amazon.com/redshift/latest/dg/copy-parameters-data-format.html#copy-json-jsonpaths


def test_copy_parquet(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://bucket/data.parquet' {iam_role} FORMAT AS PARQUET;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=s3://bucket/data.parquet]", "column[fruit.simple.name]"],
        ["column[age path=s3://bucket/data.parquet]", "column[fruit.simple.age]"],
    ]
    assert h.nodes_full == [
        'column[age type=INT kind=file format=PARQUET path=s3://bucket/data.parquet]',
        'column[name type=VARCHAR kind=file format=PARQUET path=s3://bucket/data.parquet]',
        'column[name=age table=simple schema=fruit type=INT kind=table]',
        'column[name=name table=simple schema=fruit type=VARCHAR kind=table]',
    ]


def test_copy_no_data(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://bucket/path' {iam_role} NOLOAD;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.edges) == 0
    assert h.query_types == [TableQuery, CopyQuery]
    assert len(h.lineage.collected_queries.queries) == 2

#
# def test_copy_job(holder):
#     sql = f"""
#     {simple_table}
#     COPY fruit.simple FROM 's3://path' {iam_role} JOB CREATE my_job;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     assert h.paths == [
#         ["column[name path=s3://path]", "column[fruit.simple.name]"],
#         ["column[age path=s3://path]", "column[fruit.simple.age]"],
#     ]
