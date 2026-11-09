import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__ordinality_counter_source(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INT);

    INSERT INTO target (name, age)
    SELECT src.name, src.age FROM UNNEST(ARRAY['a']) WITH ORDINALITY AS src(name, age);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes_full == [
        "counter[position[query_depth=0 query_width=0 statement=1 select=1 func_depth=0 func_arg=0]]",
        "function[name=UNNEST type=VARCHAR position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "literal[name={'a'} type=ARRAY<VARCHAR> position=[query_depth=0 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "column[name=age type=VARCHAR properties=[kind=udtf table=src]]",
        "column[name=name type=VARCHAR properties=[kind=udtf table=src]]",
        "column[name=age type=INT properties=[kind=table table=target schema=public]]",
        "column[name=name type=TEXT properties=[kind=table table=target schema=public]]",
    ]
    assert h.paths == [
        ["literal[{'a'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
    ]


def test__ordinality_counter_unique_per_query(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INT);

    INSERT INTO target (name, age)
    SELECT src.name, src.age FROM UNNEST(ARRAY['a']) WITH ORDINALITY AS src(name, age);

    INSERT INTO target (name, age)
    SELECT src.name, src.age FROM UNNEST(ARRAY['b']) WITH ORDINALITY AS src(name, age);
    """
    h = holder(sql=sql, dialect=DIALECT)

    # TODO: table alias columns should have positions to make them unique
    assert h.nodes == [
        "counter[]",
        "counter[]",
        "function[UNNEST]",
        "function[UNNEST]",
        "literal[{'a'}]",
        "literal[{'b'}]",
        "column[src.age]",
        "column[src.name]",
        "column[public.target.age]",
        "column[public.target.name]",
    ]
    assert h.paths == [
        ["literal[{'a'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["literal[{'a'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
        ["literal[{'b'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["literal[{'b'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
    ]


def test__ordinality_lateral_counter_source(holder):
    sql = """
    CREATE TABLE source (id INT, tags TEXT[]);
    CREATE TABLE target (id INT, tag TEXT, pos INT);

    INSERT INTO target (id, tag, pos)
    SELECT s.id, x.tag, x.n FROM source s, LATERAL UNNEST(s.tags) WITH ORDINALITY AS x(tag, n);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes == [
        "counter[]",
        "function[UNNEST]",
        "column[x.n]",
        "column[x.tag]",
        "column[public.source.id]",
        "column[public.source.tags]",
        "column[public.target.id]",
        "column[public.target.pos]",
        "column[public.target.tag]",
    ]
    assert h.paths == [
        ["column[public.source.id]", "column[public.target.id]"],
        ["column[public.source.tags]", "function[UNNEST]", "column[x.tag]", "column[public.target.tag]"],
        ["counter[]", "column[x.n]", "column[public.target.pos]"],
    ]


def test__ordinality_non_ordinal_column_has_no_counter(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INT);

    INSERT INTO target (name, age)
    SELECT src.name, src.age FROM UNNEST(ARRAY['a']) WITH ORDINALITY AS src(name, age);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.nodes == [
        "counter[]",
        "function[UNNEST]",
        "literal[{'a'}]",
        "column[src.age]",
        "column[src.name]",
        "column[public.target.age]",
        "column[public.target.name]",
    ]
    assert h.paths == [
        ["literal[{'a'}]", "function[UNNEST]", "column[src.name]", "column[public.target.name]"],
        ["counter[]", "column[src.age]", "column[public.target.age]"],
    ]
