import os
import sys

from sqlleaf.models.query import SetQuery
from tests.new_fixtures import holder as holder

import sqlglot

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__set_search_path_changes_catalog(holder):
    sql = """
    SET search_path = app, public;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.current_user_catalog == "app"


def test__set_search_path_to_syntax(holder):
    sql = """
    SET search_path TO reporting;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.current_user_catalog == "reporting"


def test__set_search_path_skips_user_placeholder(holder):
    sql = """
    SET search_path = "$user", app;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.current_user_catalog == "app"


def test__set_search_path_affects_table_resolution(holder):
    sql = """
    CREATE TABLE public.users (id INT, name TEXT);
    CREATE TABLE app.users (id INT, email TEXT);
    CREATE TABLE app.report (email TEXT);

    SET search_path = app, public;

    INSERT INTO app.report (email) SELECT email FROM users;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.lineage.object_mapping.current_user_catalog == "app"
    assert h.paths == [["column[app.users.email]", "column[app.report.email]"]]
    assert len(h.edges) == 1


def test__set_search_path_unsupported_by_sqlglot():
    sql = """
    SET search_path = app, public;
    """
    result = sqlglot.parse_one(sql, dialect=DIALECT)
    assert isinstance(result, sqlglot.exp.Command)


def test__set_session_search_path_changes_catalog(holder):
    sql = """
    SET SESSION search_path = app, public;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert [SetQuery] == h.query_types
    assert h.lineage.object_mapping.current_user_catalog == "app"


def test__set_search_path_to_default_restores_default_catalog(holder):
    sql = """
    SET search_path TO app;
    SET search_path TO DEFAULT;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.lineage.object_mapping.current_user_catalog == "public"
