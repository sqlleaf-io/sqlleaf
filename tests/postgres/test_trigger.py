import os
import sys

import pytest

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


@pytest.mark.skip(reason="todo")
def test_trigger_before_insert(holder):
    sql = """
    CREATE TRIGGER before_fruit_insert
    BEFORE INSERT ON fruit.processed
    FOR EACH ROW
    EXECUTE FUNCTION check_fruit();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_after_update(holder):
    sql = """
    CREATE TRIGGER after_fruit_update
    AFTER UPDATE ON fruit.processed
    FOR EACH ROW
    EXECUTE FUNCTION log_update();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_after_delete_statement(holder):
    sql = """
    CREATE TRIGGER after_fruit_delete
    AFTER DELETE ON fruit.processed
    FOR EACH STATEMENT
    EXECUTE FUNCTION cleanup_audit();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_before_truncate(holder):
    sql = """
    CREATE TRIGGER before_fruit_truncate
    BEFORE TRUNCATE ON fruit.processed
    FOR EACH STATEMENT
    EXECUTE FUNCTION notify_truncate();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_after_insert_referencing(holder):
    sql = """
    CREATE TRIGGER after_fruit_insert_ref
    AFTER INSERT ON fruit.processed
    REFERENCING NEW TABLE AS new_fruit
    FOR EACH STATEMENT
    EXECUTE FUNCTION sync_to_backup();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_before_update_of_column(holder):
    sql = """
    CREATE TRIGGER before_fruit_update_name
    BEFORE UPDATE OF name ON fruit.processed
    FOR EACH ROW
    EXECUTE FUNCTION validate_name();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)


@pytest.mark.skip(reason="todo")
def test_trigger_instead_of_insert(holder):
    sql = """
    CREATE TRIGGER instead_of_fruit_insert
    INSTEAD OF INSERT ON fruit.processed_view
    FOR EACH ROW
    EXECUTE FUNCTION route_insert();
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)
