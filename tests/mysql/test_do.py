import os
import sys

import pytest
import sqlglot

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__do_fails(holder):
    with pytest.raises(sqlglot.errors.ParseError) as e:
        sql = """
        DO SLEEP(5);
        """
        holder(sql=sql, dialect=DIALECT)
    assert e.value.args[0].startswith("Invalid expression / Unexpected token.")
