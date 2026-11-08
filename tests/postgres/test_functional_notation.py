import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__fn_select(holder):
    sql = """
    CREATE TABLE source(name VARCHAR);
    CREATE TABLE target(name VARCHAR);

    INSERT INTO public.target (name) SELECT name(source) FROM public.source;
    """
    h = holder(sql=sql, dialect=DIALECT)
    # Find the INSERT holder explicitly (avoid relying on statement index ordering)
    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT source.name AS name FROM public.source AS source"
    )
    assert h.paths == [["column[public.source.name]", "column[public.target.name]"]]
    assert h.nodes_full == [
        "column[name=name type=VARCHAR properties=[kind=table table=source schema=public]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target schema=public]]",
    ]


def test__fn_select_alias(holder):
    sql = """
    CREATE TABLE source(name VARCHAR);
    CREATE TABLE target(name VARCHAR);

    INSERT INTO public.target (name) SELECT name(s) FROM public.source s;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert (
        h.holders[2].transformed.statement.sql(dialect=DIALECT)
        == "INSERT INTO public.target (name) SELECT s.name AS name FROM public.source AS s"
    )
    assert h.paths == [["column[public.source.name]", "column[public.target.name]"]]
    assert h.nodes_full == [
        "column[name=name type=VARCHAR properties=[kind=table table=source schema=public]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target schema=public]]",
    ]
