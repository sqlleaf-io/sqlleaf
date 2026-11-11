import os
import sys

from tests.new_fixtures import assert_query_does_nothing, holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


def test_alter_table_append(holder):
    sql = """
    CREATE TABLE target_table_name(name VARCHAR, amount INT);
    CREATE TABLE source_table_name(name VARCHAR, amount INT);

    ALTER TABLE target_table_name APPEND FROM source_table_name;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert_query_does_nothing(h)
    assert len(h.collected_queries.unsupported) == 1
