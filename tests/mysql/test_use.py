import os
import sys

from sqlleaf.models.query import UseQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def test__use(holder):
    sql = """
    USE sales;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [UseQuery] == h.query_types
    assert h.lineage.object_mapping.current_database == "sales"


def test__use_qualifies_unqualified_tables(holder):
    sql = """
    CREATE TABLE sales.orders (amount INT);
    CREATE TABLE sales.report (amount INT);

    USE sales;

    INSERT INTO report (amount) SELECT amount FROM orders;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[sales.orders.amount]", "column[sales.report.amount]"]]
    assert len(h.edges) == 1
