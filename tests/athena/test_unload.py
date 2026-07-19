import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


# This is a parser bug; fails if 'CREATE TABLE' precedes 'UNLOAD'
def test__unload_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        CREATE TABLE source(name VARCHAR, amount INT);
    
        UNLOAD ('SELECT * FROM source')
        TO 's3://object-path/name-prefix'
        IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
        """
        h = holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token. Line 5, Col: 41.")
