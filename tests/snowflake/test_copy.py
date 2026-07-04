import os
import sys

import pytest

from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlleaf.models.query import CopyQuery, StageQuery, TableQuery

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
        [f"column[NAME stage={new} path=s3://load/files/]", "column[INCOMING.ZONE.NAME]"],
        [f"column[AGE stage={new} path=s3://load/files/]", "column[INCOMING.ZONE.AGE]"],
    ]
    assert h.nodes_full == [
        f"column[name=AGE type=INT properties=[kind=stage stage={new} path=s3://load/files/]]",
        f"column[name=NAME type=VARCHAR properties=[kind=stage stage={new} path=s3://load/files/]]",
        "column[name=AGE type=INT properties=[kind=table table=ZONE schema=INCOMING]]",
        "column[name=NAME type=VARCHAR properties=[kind=table table=ZONE schema=INCOMING]]",
    ]
    assert len(h.edges) == 2
    query: CopyQuery = h.queries_original[2]
    assert query.source_info.type == SqlObjectType.STAGE
    assert query.target_info.type == SqlObjectType.TABLE


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
        ["column[OUTGOING.ZONE.NAME]", f"column[NAME stage={new} path=s3://load/files/]"],
        ["column[OUTGOING.ZONE.AGE]", f"column[AGE stage={new} path=s3://load/files/]"],
    ]
    assert h.nodes_full == [
        f"column[name=AGE type=INT properties=[kind=stage stage={new} path=s3://load/files/]]",
        f"column[name=NAME type=VARCHAR properties=[kind=stage stage={new} path=s3://load/files/]]",
        "column[name=AGE type=INT properties=[kind=table table=ZONE schema=OUTGOING]]",
        "column[name=NAME type=VARCHAR properties=[kind=table table=ZONE schema=OUTGOING]]",
    ]
    query: CopyQuery = h.queries_original[2]
    assert query.source_info.type == SqlObjectType.TABLE
    assert query.target_info.type == SqlObjectType.STAGE


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

    assert [TableQuery, TableQuery, StageQuery, CopyQuery, CopyQuery] == h.query_types
    assert h.nodes_full == [
        f"column[name=AGE type=INT properties=[kind=stage stage={new} path=s3://load/files/]]",
        f"column[name=NAME type=VARCHAR properties=[kind=stage stage={new} path=s3://load/files/]]",
        "column[name=AGE type=INT properties=[kind=table table=ZONE schema=INCOMING]]",
        "column[name=NAME type=VARCHAR properties=[kind=table table=ZONE schema=INCOMING]]",
        "column[name=AGE type=INT properties=[kind=table table=ZONE schema=OUTGOING]]",
        "column[name=NAME type=VARCHAR properties=[kind=table table=ZONE schema=OUTGOING]]",
    ]
    assert h.paths == [
        ["column[OUTGOING.ZONE.NAME]", f"column[NAME stage={new} path=s3://load/files/]", "column[INCOMING.ZONE.NAME]"],
        ["column[OUTGOING.ZONE.AGE]", f"column[AGE stage={new} path=s3://load/files/]", "column[INCOMING.ZONE.AGE]"],
    ]
    query_1: CopyQuery = h.queries_original[3]
    assert query_1.source_info.type == SqlObjectType.STAGE
    assert query_1.target_info.type == SqlObjectType.TABLE

    query_2: CopyQuery = h.queries_original[4]
    assert query_2.source_info.type == SqlObjectType.TABLE
    assert query_2.target_info.type == SqlObjectType.STAGE
    # TODO: full names should include the stage's s3 file path
