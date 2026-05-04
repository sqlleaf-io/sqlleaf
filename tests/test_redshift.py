import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


from tests.new_fixtures import (
    holder,
)

DIALECT = "redshift"


def test__select_pivot(holder):
    queries = """
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
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    assert paths == [
        ['column[source.age]', 'column[_0.age]', 'column[target.john_average]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.john_total]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.mary_average]'],
        ['column[source.age]', 'column[_0.age]', 'column[target.mary_total]']
    ]
    assert nodes == [
        'column[_0.age type=INT kind=pivot]',
        'column[source.age type=INT kind=table]',
        'column[target.john_average type=DECIMAL(10, 2) kind=table]',
        'column[target.john_total type=INT kind=table]',
        'column[target.mary_average type=DECIMAL(10, 2) kind=table]',
        'column[target.mary_total type=INT kind=table]'
    ]
    assert len(edges) == 5
    # TODO: the agg functions used inside the pivot are currently not extracted.


def test__unload(holder):
    queries = """
    UNLOAD ('SELECT * FROM fruit.raw')
    TO 's3://object-path/name-prefix'
    IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
    """
    h = holder(with_tables=True)
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    edges = h.get_edges()
    paths = h.get_friendly_paths()
    queries = h.get_queries_created()

    assert len(nodes) == 0
    assert len(queries) == 0
    # TODO: the agg functions used inside the pivot are currently not extracted.
