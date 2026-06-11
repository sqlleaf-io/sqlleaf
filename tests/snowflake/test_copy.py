import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


from sqlleaf.objects.query_types import CopyQuery, StageQuery, TableQuery

DIALECT = "snowflake"

cases = [
    # Snowflake converts to uppercase unless double-quoted
    ('"my_eXt_sTaGe"', "my_eXt_sTaGe"),  # fmt: skip
    ("my_eXt_sTaGe", "MY_EXT_STAGE"),
]


@pytest.mark.parametrize("case", cases)
def test___copy_from_stage(holder, case):
    old, new = case
    sql = f"""
    CREATE TABLE incoming.zone (name VARCHAR, age INT);

    CREATE STAGE {old}
      URL='s3://load/files/'
      STORAGE_INTEGRATION = myint;

    COPY INTO incoming.zone
    FROM @{old}
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [f"column[NAME stage={new}]", "column[INCOMING.ZONE.NAME]"],
        [f"column[AGE stage={new}]", "column[INCOMING.ZONE.AGE]"],
    ]
    assert h.nodes_full == [
        f"column[AGE type=INT kind=stage stage={new}]",
        f"column[NAME type=VARCHAR kind=stage stage={new}]",
        "column[name=AGE table=ZONE schema=INCOMING type=INT kind=table]",
        "column[name=NAME table=ZONE schema=INCOMING type=VARCHAR kind=table]",
    ]


@pytest.mark.parametrize("case", cases)
def test___copy_to_stage(holder, case):
    old, new = case
    sql = f"""
    CREATE TABLE outgoing.zone (name VARCHAR, age INT);

    CREATE STAGE {old}
      URL='s3://load/files/'
      STORAGE_INTEGRATION = myint;

    COPY INTO @{old}
    FROM outgoing.zone
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[OUTGOING.ZONE.NAME]", f"column[NAME stage={new}]"],
        ["column[OUTGOING.ZONE.AGE]", f"column[AGE stage={new}]"],
    ]
    assert h.nodes_full == [
        f"column[AGE type=INT kind=stage stage={new}]",
        f"column[NAME type=VARCHAR kind=stage stage={new}]",
        "column[name=AGE table=ZONE schema=OUTGOING type=INT kind=table]",
        "column[name=NAME table=ZONE schema=OUTGOING type=VARCHAR kind=table]",
    ]


@pytest.mark.parametrize("case", cases)
def test___copy_to_and_from_stage(holder, case):
    old, new = case
    sql = f"""
    CREATE TABLE incoming.zone (name VARCHAR, age INT);
    CREATE TABLE outgoing.zone (name VARCHAR, age INT);

    CREATE STAGE {old}
      URL='s3://load/files/'
      STORAGE_INTEGRATION = myint;

    COPY INTO incoming.zone
    FROM @{old}
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );

    COPY INTO @{old}
    FROM outgoing.zone
    FILE_FORMAT = ( TYPE = 'CSV', FIELD_DELIMITER = ',', SKIP_HEADER = 1 );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [TableQuery, TableQuery, StageQuery, CopyQuery, CopyQuery] == list(map(type, h.queries))
    assert h.nodes_full == [
        f"column[AGE type=INT kind=stage stage={new}]",
        f"column[NAME type=VARCHAR kind=stage stage={new}]",
        "column[name=AGE table=ZONE schema=INCOMING type=INT kind=table]",
        "column[name=NAME table=ZONE schema=INCOMING type=VARCHAR kind=table]",
        "column[name=AGE table=ZONE schema=OUTGOING type=INT kind=table]",
        "column[name=NAME table=ZONE schema=OUTGOING type=VARCHAR kind=table]",
    ]
    assert h.paths == [
        ["column[OUTGOING.ZONE.NAME]", f"column[NAME stage={new}]", "column[INCOMING.ZONE.NAME]"],
        ["column[OUTGOING.ZONE.AGE]", f"column[AGE stage={new}]", "column[INCOMING.ZONE.AGE]"],
    ]
    # TODO: full names should include the stage's s3 file path
