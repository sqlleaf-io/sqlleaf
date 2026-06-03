from tests.new_fixtures import holder as holder
import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


DIALECT = "postgres"


@pytest.mark.skip(reason="todo")
def test__trigger_before_insert(holder):
    sql = """
    CREATE TRIGGER before_fruit_insert
    BEFORE INSERT ON fruit.processed
    FOR EACH ROW
    EXECUTE FUNCTION check_fruit();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert {"fruit.b_like_a.label", "fruit.b_like_a.name", "fruit.b_like_a.age"}.issubset(h.nodes)
    assert len(h.nodes) == 6
    assert len(h.edges) == 3
