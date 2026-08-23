import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "snowflake"


def test__volume_s3(holder):
    sql = """
    CREATE OR REPLACE EXTERNAL VOLUME exvol
    STORAGE_LOCATIONS =
      (
        (
            NAME = 'my-s3-us-west-2'
            STORAGE_PROVIDER = 'S3'
            STORAGE_BASE_URL = 's3://my-example-bucket/'
            STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::123456789012:role/myrole'
            ENCRYPTION = ( TYPE = 'AWS_SSE_KMS' KMS_KEY_ID = '1234abcd-12ab-34cd-56ef-1234567890ab' )
        )
      )
    ALLOW_WRITES = TRUE;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
