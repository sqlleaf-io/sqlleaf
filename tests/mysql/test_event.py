import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "mysql"


def test_event_at_schedule_unsupported(holder):
    sql = """
    CREATE EVENT my_event
    ON SCHEDULE AT CURRENT_TIMESTAMP + INTERVAL 1 HOUR
    DO UPDATE t1 SET c1 = c1 + 1;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.query_types == []
    assert len(h.collected_queries.unsupported) == 1


def test_event_every_schedule_unsupported(holder):
    sql = """
    CREATE EVENT my_event
    ON SCHEDULE EVERY 1 DAY
    STARTS CURRENT_TIMESTAMP
    ENDS CURRENT_TIMESTAMP + INTERVAL 1 MONTH
    DO CALL purge_logs();
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.query_types == []
    assert len(h.collected_queries.unsupported) == 1


def test_event_on_completion_unsupported(holder):
    sql = """
    CREATE EVENT my_event
    ON SCHEDULE AT '2026-01-01 00:00:00'
    ON COMPLETION PRESERVE
    DO SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.query_types == []
    assert len(h.collected_queries.unsupported) == 1


def test_event_status_unsupported(holder):
    sql = """
    CREATE EVENT my_event
    ON SCHEDULE EVERY 1 HOUR
    DISABLE
    DO SELECT 1;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == []
    assert h.query_types == []
    assert len(h.collected_queries.unsupported) == 1
