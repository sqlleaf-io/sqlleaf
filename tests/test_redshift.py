import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import (
    holder,
)

DIALECT = "redshift"


def test__select_pivot_no_alias(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);
    CREATE TABLE target(john_total INT);

    INSERT INTO target
    SELECT * FROM (
      SELECT name, amount
      FROM source
    )
    PIVOT (
      SUM(amount)
      FOR name IN ('john')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [['column[source.amount]', 'column[_0.amount]', 'function[SUM]', 'pivot[]', 'column[target.john_total]']]
    assert h.nodes_full == [
        'pivot[source= target=john statement=2]',
        'function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        'column[_0.amount type=INT kind=derived_table]',
        'column[source.amount type=INT kind=table]',
        'column[target.john_total type=INT kind=table]'
    ]
    assert len(h.edges) == 4


def test__select_pivot_alias(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, age INT, amount INT);
    CREATE TABLE target(john_total INT, john_average DECIMAL(10,2), mary_total INT, mary_average DECIMAL(10,2));

    INSERT INTO target
    SELECT * FROM (
      SELECT name, age, amount
      FROM source
    )
    PIVOT (
      SUM(amount) as total,
      AVG(age) as average
      FOR name IN ('john', 'mary')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[source.amount]', 'column[_0.amount]', 'function[SUM]', 'pivot[]', 'column[target.john_total]'],
        ['column[source.amount]', 'column[_0.amount]', 'function[SUM]', 'pivot[]', 'column[target.mary_total]'],
        ['column[source.age]', 'column[_0.age]', 'function[AVG]', 'pivot[]', 'column[target.john_average]'],
        ['column[source.age]', 'column[_0.age]', 'function[AVG]', 'pivot[]', 'column[target.mary_average]']
    ]
    assert h.nodes_full == [
        'pivot[source=total target=john_total statement=2]',
        'pivot[source=average target=john_average statement=2]',
        'pivot[source=total target=mary_total statement=2]',
        'pivot[source=average target=mary_average statement=2]',
        'function[AVG type=DOUBLE query_depth=0 query_width=0 statement=2 select=1 func_depth=0 func_arg=0]',
        'function[AVG type=DOUBLE query_depth=0 query_width=0 statement=2 select=3 func_depth=0 func_arg=0]',
        'function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        'function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=2 func_depth=0 func_arg=0]',
        'column[_0.age type=INT kind=derived_table]',
        'column[_0.amount type=INT kind=derived_table]',
        'column[source.age type=INT kind=table]',
        'column[source.amount type=INT kind=table]',
        'column[target.john_average type=DECIMAL(10, 2) kind=table]',
        'column[target.john_total type=INT kind=table]',
        'column[target.mary_average type=DECIMAL(10, 2) kind=table]',
        'column[target.mary_total type=INT kind=table]'
    ]
    assert len(h.edges) == 14


def test__unload(holder):
    sql = """
    UNLOAD ('SELECT * FROM fruit.raw')
    TO 's3://object-path/name-prefix'
    IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert len(h.nodes) == 0
    assert len(h.queries) == 0


def test__table_external(holder):
    sql = """
    CREATE EXTERNAL TABLE fruit.ext (
        name VARCHAR,
        age INT
    )
    ROW FORMAT DELIMITED
    FIELDS TERMINATED BY '\t'
    STORED AS TEXTFILE
    LOCATION 's3://my-bucket/new/fruit/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['column[name s3://my-bucket/new/fruit/]', 'column[fruit.ext.name]'],
        ['column[age s3://my-bucket/new/fruit/]', 'column[fruit.ext.age]']
    ]
    assert "column[name type=UNKNOWN kind=file format=TEXTFILE path=s3://my-bucket/new/fruit/]" in h.nodes_full
    assert "column[fruit.ext.age type=INT kind=table subkind=external]" in h.nodes_full
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_unpivot(holder):
    sql = """
    CREATE TABLE source(john_total INT);
    CREATE TABLE target(name VARCHAR, amount INT);

    INSERT INTO target
    SELECT name, amount
    FROM source
    UNPIVOT (
      amount FOR name IN (john_total AS 'john')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["john"]', 'unpivot[]', 'column[target.name]'],
        ['column[source.john_total]', 'unpivot[]', 'column[target.amount]']
    ]
    assert h.nodes_full == [
        'unpivot[source= target=name statement=2]',
        'unpivot[source=john_total target=amount statement=2]',
        'literal["john" type=VARCHAR query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        'column[source.john_total type=INT kind=table]',
        'column[target.amount type=INT kind=table]',
        'column[target.name type=VARCHAR kind=table]'
    ]
    assert len(h.edges) == 4

# TODO: -- Multiple output columns
#  UNPIVOT (
#   (amount, quantity)
#   FOR name IN (
#     (john_total, john_count) AS 'john',
#     (jane_total, jane_count) AS 'jane'
#   )
# );

# TODO: -- Multiple UNPIVOTs
#  UNPIVOT (amount FOR name IN (...))
#  UNPIVOT (rating FOR category IN (...));
