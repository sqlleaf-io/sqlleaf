import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


# TODO: UNNEST()


def test__select_pseudocolumns(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target (name) SELECT "$path" FROM source WHERE "$path" LIKE '%2023-01-01%';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.$path]", "column[target.name]"]]
    assert h.nodes_full == [
        "column[name=$path type=VARCHAR properties=[kind=table table=source]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 1


def test__cte_struct_one_column(holder):
    sql = """
    CREATE TABLE target (name struct<first:VARCHAR>);

    WITH dataset AS (
      SELECT CAST(ROW('Bob') AS ROW(first VARCHAR)) AS users
    )
    INSERT INTO target (name)
    SELECT dataset.users FROM dataset
    """
    # +--------------------+
    # | name               |
    # +--------------------+
    # | {FIRST=Bob}        |
    # +--------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["Bob"]', "function[ROW]", "function[CAST]", "column[dataset.users]", "column[target.name]"]
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        "function[name=CAST type=STRUCT<first VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "column[name=users type=STRUCT<first VARCHAR> properties=[kind=cte table=dataset statement=1]]",
        "column[name=name type=STRUCT<first VARCHAR> properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 4


def test__cte_struct_two_columns(holder):
    sql = """
    CREATE TABLE target (name struct<first:VARCHAR, last:VARCHAR>);

    WITH dataset AS (
      SELECT CAST(ROW('Bob', 'Smith') AS ROW(first VARCHAR, last VARCHAR)) AS users
    )
    INSERT INTO target (name)
    SELECT dataset.users FROM dataset
    """
    # +------------------------+
    # | name                   |
    # +------------------------+
    # | {FIRST=Bob,LAST=Smith} |
    # +------------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["Bob"]', "function[ROW]", "function[CAST]", "column[dataset.users]", "column[target.name]"],
        ['literal["Smith"]', "function[ROW]", "function[CAST]", "column[dataset.users]", "column[target.name]"],
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        'literal[name="Smith" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]',
        "function[name=CAST type=STRUCT<first VARCHAR, last VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR, VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "column[name=users type=STRUCT<first VARCHAR, last VARCHAR> properties=[kind=cte table=dataset statement=1]]",
        "column[name=name type=STRUCT<first VARCHAR, last VARCHAR> properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 5


def test__cte_with_row_complex(holder):
    sql = """
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    WITH dataset AS (
      SELECT
        CAST(
          ROW('Bob', ROW('Smith')) AS ROW(first_name VARCHAR, other ROW(last_name VARCHAR))
        ) AS people
    )
    INSERT INTO target (first, last)
    SELECT people.first_name, people.other.last_name
    FROM dataset;
    """
    # +--------------------------------------------+
    # | people                                     |
    # +--------------------------------------------+
    # | {FIRST_NAME=Bob, OTHER={LAST_NAME=Smith}}  |
    # +--------------------------------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["Bob"]', "function[ROW]", "function[CAST]", "column[dataset.people]", "column[target.first]"],
        ['literal["Bob"]', "function[ROW]", "function[CAST]", "column[dataset.people]", "column[target.last]"],
        [
            'literal["Smith"]',
            "function[ROW]",
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[target.first]",
        ],
        [
            'literal["Smith"]',
            "function[ROW]",
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[target.last]",
        ],
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        'literal[name="Smith" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=3 func_arg=1]]',
        "function[name=CAST type=STRUCT<first_name VARCHAR, other STRUCT<last_name VARCHAR>> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR, STRUCT<VARCHAR>> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]",
        "column[name=people type=STRUCT<first_name VARCHAR, other STRUCT<last_name VARCHAR>> properties=[kind=cte table=dataset statement=1]]",
        "column[name=first type=VARCHAR properties=[kind=table table=target]]",
        "column[name=last type=VARCHAR properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 7
