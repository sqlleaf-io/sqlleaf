import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__view_protected_multi_dialect(holder):
    sql = """
    CREATE PROTECTED MULTI DIALECT VIEW orders_by_date 
    SECURITY DEFINER 
    AS 
    SELECT orderdate, sum(totalprice) AS price 
    FROM orders 
    WHERE order_city = 'SEATTLE' 
    GROUP BY orderdate
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert len(h.collected_queries.unsupported) == 1
