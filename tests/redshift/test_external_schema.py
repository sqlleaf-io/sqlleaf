import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

"""
CREATE EXTERNAL SCHEMA [IF NOT EXISTS] local_schema_name
FROM [ [ DATA CATALOG ] | HIVE METASTORE | POSTGRES | MYSQL | KINESIS | MSK | REDSHIFT | KAFKA ]
[ DATABASE 'database_name' ]
[ SCHEMA 'schema_name' ]
[ REGION 'aws-region' ]
[ IAM_ROLE [ default | 'SESSION' | 'arn:aws:iam::<AWS account-id>:role/<role-name>' ] ]
[ AUTHENTICATION [ none | iam | mtls] ]
[ AUTHENTICATION_ARN 'acm-certificate-arn' | SECRET_ARN 'ssm-secret- arn' ]
[ URI ['hive_metastore_uri' [ PORT port_number ] | 'hostname' [ PORT port_number ] | 'Kafka bootstrap URL'] ]
[ CLUSTER_ARN 'arn:aws:kafka:<region>:<AWS account-id>:cluster/msk/<cluster uuid>' ]
[ CATALOG_ROLE [ 'SESSION' | 'catalog-role-arn-string' ] ]
[ CREATE EXTERNAL DATABASE IF NOT EXISTS ]
[ CATALOG_ID 'Amazon Web Services account ID containing Glue or Lake Formation database' ]
"""

DIALECT = "redshift"


# def test__example(holder):
#     sql = """
#     CREATE TABLE fruit.cooked (col1, col2) AS
#     SELECT name, kind FROM fruit.raw;
#     """
#     h = holder(sql=sql, dialect=DIALECT, with_tables=True)
#
#     assert h.paths == [
#         ["column[fruit.raw.name]", "column[fruit.cooked.col1]"],
#         ["column[fruit.raw.kind]", "column[fruit.cooked.col2]"],
#     ]
#     assert len(h.nodes) == 4
#     assert len(h.edges) == 2


#
# def test__example_fails(holder):
#     with pytest.raises(ParseError) as e:
#         sql = """
#         COPY (INSERT INTO fruit.simple (name) VALUES ('cherry') RETURNING name) TO STDOUT;
#         """
#         h = holder(sql=sql, dialect=DIALECT)
#         assert h.paths == [
#             ['literal["cherry"]', "column[fruit.simple.name]", "stream[stdout]"],
#         ]
#     assert e.value.args[0].startswith("Expecting ). Line 3, Col: 20.")


def test__external_schema_data_catalog(holder):
    sql = """
    CREATE EXTERNAL SCHEMA spectrum_schema
    FROM DATA CATALOG
    DATABASE 'spectrumdb'
    IAM_ROLE 'arn:aws:iam::123456789012:role/MyRedshiftRole'
    CREATE EXTERNAL DATABASE IF NOT EXISTS;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_data_catalog_if_not_exists(holder):
    sql = """
    CREATE EXTERNAL SCHEMA IF NOT EXISTS spectrum_schema
    FROM DATA CATALOG
    DATABASE 'spectrumdb'
    REGION 'us-east-1'
    IAM_ROLE default
    CATALOG_ID '123456789012';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_hive_metastore(holder):
    sql = """
    CREATE EXTERNAL SCHEMA hive_schema
    FROM HIVE METASTORE
    DATABASE 'hive_db'
    URI '172.10.10.10' PORT 9083
    IAM_ROLE default;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_postgres(holder):
    sql = """
    CREATE EXTERNAL SCHEMA pg_schema
    FROM POSTGRES
    DATABASE 'pgdb'
    SCHEMA 'public'
    URI 'hostname' PORT 5432
    IAM_ROLE default
    SECRET_ARN 'arn:aws:secretsmanager:us-east-1:123456789012:secret:pg-abc';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_mysql(holder):
    sql = """
    CREATE EXTERNAL SCHEMA mysql_schema
    FROM MYSQL
    DATABASE 'mydb'
    URI 'hostname' PORT 3306
    IAM_ROLE default
    SECRET_ARN 'arn:aws:secretsmanager:us-east-1:123456789012:secret:my-abc';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_kinesis(holder):
    sql = """
    CREATE EXTERNAL SCHEMA kinesis_schema
    FROM KINESIS
    IAM_ROLE 'arn:aws:iam::123456789012:role/MyRedshiftRole';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_msk(holder):
    sql = """
    CREATE EXTERNAL SCHEMA msk_schema
    FROM MSK
    IAM_ROLE 'arn:aws:iam::123456789012:role/MyRedshiftRole'
    AUTHENTICATION iam
    CLUSTER_ARN 'arn:aws:kafka:us-east-1:123456789012:cluster/msk/abc-123';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_redshift(holder):
    sql = """
    CREATE EXTERNAL SCHEMA rs_schema
    FROM REDSHIFT
    DATABASE 'db'
    SCHEMA 'public'
    REGION 'us-east-1'
    IAM_ROLE default;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1


def test__external_schema_kafka(holder):
    sql = """
    CREATE EXTERNAL SCHEMA kafka_schema
    FROM KAFKA
    URI 'broker:9092'
    AUTHENTICATION none;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1
