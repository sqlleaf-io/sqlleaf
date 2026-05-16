import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import (
    holder,
)

DIALECT = "redshift"


# TODO: SELECT (SELECT PIVOT)

def test__select_pivot(holder):
    sql = """
    CREATE TABLE source(name1 VARCHAR, name2 VARCHAR, age INT);
    CREATE TABLE target(john_total INT, mary_total INT, john_average DECIMAL(10,2), mary_average DECIMAL(10,2));

    INSERT INTO target
    SELECT * FROM (
      SELECT name1, age
      FROM source
    )
    PIVOT (
      SUM(age) as total,
      AVG(age) as average
      FOR name1 IN ('john', 'mary')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)
    assert h.paths == [
        ['column[source.age]', 'column[_0.age]', 'column[target.john_average]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.john_total]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.mary_average]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.mary_total]']
    ]
    assert h.nodes_full == [
        'column[_0.age type=INT kind=pivot]',
        'column[source.age type=INT kind=table]',
        'column[target.john_average type=DECIMAL(10, 2) kind=table]',
        'column[target.john_total type=INT kind=table]',
        'column[target.mary_average type=DECIMAL(10, 2) kind=table]',
        'column[target.mary_total type=INT kind=table]'
    ]
    assert len(h.edges) == 5
    # TODO: the agg functions used inside the pivot are currently not extracted.


def test__unload(holder):
    sql = """
    UNLOAD ('SELECT * FROM fruit.raw')
    TO 's3://object-path/name-prefix'
    IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert len(h.nodes) == 0
    assert len(h.queries) == 0
    # TODO: the agg functions used inside the pivot are currently not extracted.


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
