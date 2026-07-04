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
        "column[name=amount type=INT properties=[kind=file format=UNKNOWN path=s3://object-path/name-prefix]]",
        "column[name=name type=VARCHAR properties=[kind=file format=UNKNOWN path=s3://object-path/name-prefix]]",
        "column[name=amount type=INT properties=[kind=table table=source]]",
        "column[name=name type=VARCHAR properties=[kind=table table=source]]",
    ]
    assert len(h.edges) == 2
    assert isinstance(h.queries_original[1], UnloadQuery)


# TODO: WITH FORMAT
