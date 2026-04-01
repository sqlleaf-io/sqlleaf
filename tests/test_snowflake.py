import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlleaf import structs

from tests.new_fixtures import (
    holder,
)

DIALECT = 'snowflake'

cases = [
    # Snowflake converts to uppercase unless double-quoted
    ('"my_eXt_sTaGe"', 'my_eXt_sTaGe',),
    ('my_eXt_sTaGe', "MY_EXT_STAGE"),
]

@pytest.mark.parametrize("case", cases)
def test__stage(holder, case):
    old, new = case
    queries = f'''
    CREATE TABLE landing.zone (name VARCHAR, age INT);
    
    CREATE STAGE {old}
      URL='s3://load/files/'
      STORAGE_INTEGRATION = myint;
      
    COPY INTO landing.zone
    FROM @{old}
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert [structs.TableQuery, structs.StageQuery, structs.CopyQuery] == list(map(type, queries))

    assert paths == [
        [f'column[{new}.NAME]', 'column[LANDING.ZONE.NAME]'],
        [f'column[{new}.AGE]', 'column[LANDING.ZONE.AGE]']
    ]
