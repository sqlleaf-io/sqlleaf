import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test__model(holder):
    sql = """
    CREATE MODEL customer_churn
    FROM customer_data;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.nodes) == 0
    assert len(h.edges) == 0
    assert len(h.collected_queries.unsupported) == 1
