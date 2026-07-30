import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__select_pseudocolumns(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target (name) SELECT "$path" FROM source WHERE "$path" LIKE '%2023-01-01%';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.$path]", "column[target.name]"]]
    assert h.nodes_full == [
         'column[name=$path type=VARCHAR properties=[kind=table table=source]]',
         'column[name=name type=VARCHAR properties=[kind=table table=target]]',
     ]
    assert len(h.edges) == 1


def test__cte_with_row(holder):
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

    assert h.paths == [['literal["Bob"]', 'function[ROW]', 'function[CAST]', 'column[dataset.users]', 'column[target.name]']]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        'function[name=CAST type=STRUCT<first VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]',
        'function[name=ROW type=STRUCT<VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]',
        'column[name=users type=STRUCT<first VARCHAR> properties=[kind=cte table=dataset statement=1]]',
        'column[name=name type=STRUCT<first VARCHAR> properties=[kind=table table=target]]',
    ]
    assert len(h.edges) == 4
