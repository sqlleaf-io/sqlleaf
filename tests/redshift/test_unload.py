import os
import sys

from sqlleaf.models.query import UnloadQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__unload(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);

    UNLOAD ('SELECT * FROM source')
    TO 's3://object-path/name-prefix'
    IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[name path=s3://object-path/name-prefix]"],
        ["column[source.amount]", "column[amount path=s3://object-path/name-prefix]"],
    ]
    assert h.nodes_full == [
        "column[amount type=INT kind=file format=UNKNOWN path=s3://object-path/name-prefix]",
        "column[name type=VARCHAR kind=file format=UNKNOWN path=s3://object-path/name-prefix]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=name table=source type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2
    assert isinstance(h.queries[1], UnloadQuery)
