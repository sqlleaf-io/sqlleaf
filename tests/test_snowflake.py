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

# TODO: support COPY INTO @stage FROM table
@pytest.mark.parametrize("case", cases)
def test___copy_stage(holder, case):
    old, new = case
    queries = f'''
    CREATE TABLE incoming.zone (name VARCHAR, age INT);
    
    CREATE STAGE {old}
      URL='s3://load/files/'
      STORAGE_INTEGRATION = myint;
      
    COPY INTO incoming.zone
    FROM @{old}
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert [structs.TableQuery, structs.StageQuery, structs.CopyQuery] == list(map(type, queries))
    assert paths == [
        [f'stage[{new}]', 'column[INCOMING.ZONE.AGE]'],
        [f'stage[{new}]', 'column[INCOMING.ZONE.NAME]'],
    ]


def test___put_stage(holder):
    queries = f'''
    CREATE STAGE my_int_stage
      URL='s3://load/files/';
      
    PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    queries = h.get_queries_created()
    paths = h.get_friendly_paths()

    assert [structs.StageQuery, structs.PutQuery] == list(map(type, queries))
    assert paths == [
        ['file[/tmp/data/mydata.csv]', 'stage[MY_INT_STAGE]']
    ]
