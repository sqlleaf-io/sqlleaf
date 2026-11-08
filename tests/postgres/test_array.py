import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__array_subscript_column(holder):
    sql = """
    CREATE TABLE source (my_arr integer[], num integer);
    CREATE TABLE target (first integer);

    INSERT INTO target
    SELECT my_arr[num] AS first
    FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.queries_transformed[2].statement.sql(dialect=DIALECT) == "INSERT INTO public.target (first) SELECT source.my_arr[source.num] AS first FROM public.source AS source"

    assert h.paths == [["column[public.source.my_arr]", "column[public.target.first]"]]
    assert h.nodes_full == [
        "column[name=my_arr type=ARRAY<INT> properties=[kind=table table=source schema=public]]",
        "column[name=first type=INT properties=[kind=table table=target schema=public]]",
    ]


def test__array_subscript_subquery(holder):
    sql = """
    CREATE TABLE source (my_arr integer[]);
    CREATE TABLE target (first integer);

    INSERT INTO target
    SELECT my_arr[(SELECT 4)] AS first
    FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[public.source.my_arr]", "column[public.target.first]"]]
    assert h.nodes_full == [
        "column[name=my_arr type=ARRAY<INT> properties=[kind=table table=source schema=public]]",
        "column[name=first type=INT properties=[kind=table table=target schema=public]]",
    ]


def test__array_subscript_integer(holder):
    sql = """
    CREATE TABLE source (my_arr integer[]);
    CREATE TABLE target (first integer);

    INSERT INTO target
    SELECT my_arr[0] AS first
    FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[public.source.my_arr]", "column[public.target.first]"]]
    assert h.nodes_full == [
        "column[name=my_arr type=ARRAY<INT> properties=[kind=table table=source schema=public]]",
        "column[name=first type=INT properties=[kind=table table=target schema=public]]",
    ]


def test__array_subscript_function_result(holder):
    sql = """
    CREATE TABLE source (a integer);
    CREATE TABLE target (first integer);

    INSERT INTO target
    SELECT (array_function(a))[3] AS first
    FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[public.source.a]", "function[ARRAY_FUNCTION]", "column[public.target.first]"],
    ]
    assert h.nodes_full == [
        "function[name=ARRAY_FUNCTION type=UNKNOWN position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "column[name=a type=INT properties=[kind=table table=source schema=public]]",
        "column[name=first type=INT properties=[kind=table table=target schema=public]]",
    ]
