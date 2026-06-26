import os
import sys

from sqlleaf.models.query import CopyQuery, TableQuery
from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import assert_query_does_nothing
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"

simple_table = "CREATE TABLE fruit.simple (name VARCHAR, age INT);"
iam_role = "IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole'"


def test_copy_s3_simple(holder):
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
    COPY fruit.simple FROM 'dynamodb://MyTable' {iam_role} READRATIO 50;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=dynamodb://MyTable]", "column[fruit.simple.name]"],
        ["column[age path=dynamodb://MyTable]", "column[fruit.simple.age]"],
    ]
    assert h.nodes_full == [
        "column[age type=INT kind=dynamodb table=MyTable]",
        "column[name type=VARCHAR kind=dynamodb table=MyTable]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
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
    assert h.paths == [
        ["column[name path=s3://bucket/path]", "column[#fruit.simple.name]"],
        ["column[age path=s3://bucket/path]", "column[#fruit.simple.age]"],
    ]


# TODO: JSONPaths with AVRO is extremely complex
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
        "column[age type=INT kind=file format=PARQUET path=s3://bucket/data.parquet]",
        "column[name type=VARCHAR kind=file format=PARQUET path=s3://bucket/data.parquet]",
        "column[name=age table=simple schema=fruit type=INT kind=table]",
        "column[name=name table=simple schema=fruit type=VARCHAR kind=table]",
    ]


def test_copy_no_data(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://bucket/path' {iam_role} NOLOAD;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert_query_does_nothing(h)
    assert h.query_types == [TableQuery, CopyQuery]
    assert len(h.lineage.collected_queries.queries) == 2


# #################### COPY JOBS ####################


def test_copy_job_create(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://path' {iam_role} JOB CREATE my_job;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ["column[name path=s3://path]", "column[fruit.simple.name]"],
        ["column[age path=s3://path]", "column[fruit.simple.age]"],
    ]
    assert len(h.nodes_full) == 4
    assert len(h.edges) == 2
    query: CopyQuery = h.queries_original[1]
    assert h.query_types == [TableQuery, CopyQuery]
    assert query.source_info.type == SqlObjectType.FILE
    assert query.target_info.type == SqlObjectType.TABLE


def test_copy_job_create_auto_off(holder):
    sql = f"""
    {simple_table}
    COPY fruit.simple FROM 's3://path' {iam_role} JOB CREATE my_job AUTO OFF;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert_query_does_nothing(h)

    query: CopyQuery = h.queries_original[1]
    assert h.query_types == [TableQuery, CopyQuery]
    assert query.source_info.type == SqlObjectType.FILE
    assert query.target_info.type == SqlObjectType.TABLE


# # Not supported: sqlglot parses as a regular COPY expression ('COPY job FROM run my_job')
# def test_copy_job_run(holder):
#     sql = f"""
#     {simple_table}
#     COPY fruit.simple FROM 's3://path' {iam_role} JOB CREATE my_job;
#     COPY JOB RUN my_job;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     assert h.paths == []


# # Not supported: sqlglot parses as a regular COPY expression ('COPY job FROM run my_job')
# def test_copy_job_run_error_if_not_created(holder):
#     sql = f"""
#     COPY JOB RUN my_job;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     assert h.paths == []


# # Not supported: sqlglot parses as a regular COPY expression ('COPY job FROM show my_job')
# cases = ["LIST", "SHOW my_job"]
# @pytest.mark.parametrize("case", cases)
# def test_copy_job_list_and_show(holder, case: str):
#     sql = f"""
#     COPY JOB {case};
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     assert h.paths == []


# #################### COPY TEMPLATES ####################

template_query = """
CREATE TEMPLATE test_template FOR COPY AS CSV DELIMITER '|';
"""


# Unsupported: Command
def test_template(holder):
    sql = f"""
    {template_query}
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert_query_does_nothing(h)
    assert len(h.collected_queries.unsupported) == 1


# # Strange behaviour: COPY USING TEMPLATE must have an associated CREATE TEMPLATE
# def test_copy_template_schema(holder):
#     sql = f"""
#     {simple_table}
#     {template_query}
#     COPY fruit.simple
#     FROM 's3://amzn-s3-demo-bucket/staging-folder'
#     IAM_ROLE 'arn:aws:iam::123456789012:role/MyLoadRoleName'
#     DELIMITER ','
#     USING TEMPLATE test_template;
#     """
#     h = holder(sql=sql, dialect=DIALECT)
#     assert_query_does_nothing(h)
#
#
#
# # Not supported: ParseError
# def test_copy_template_schema_errors(holder):
#     with pytest.raises(sqlglot.errors.ParseError) as e:
#         sql = f"""
#         COPY target_table
#         FROM 's3://amzn-s3-demo-bucket/staging-folder'
#         IAM_ROLE 'arn:aws:iam::123456789012:role/MyLoadRoleName'
#         DELIMITER ','
#         USING TEMPLATE public.test_template;
#         """
#         h = holder(sql=sql, dialect=DIALECT)
#
#     assert e.value.args[0].startswith("Required keyword: 'this' missing for <class 'sqlglot.expressions.dml.CopyParameter'>. Line 6, Col: 30.")
