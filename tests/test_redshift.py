import os
import sys
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlleaf import structs

from tests.new_fixtures import (
    holder,
)

DIALECT = 'redshift'

def test__select_pivot(holder):
    queries = '''
    CREATE TABLE source(name1 VARCHAR, name2 VARCHAR, age INT);
    CREATE TABLE target(john_total VARCHAR, mary_total VARCHAR, john_average VARCHAR, mary_average VARCHAR);

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
    '''
    h = holder()
    h.generate(queries, dialect=DIALECT)
    nodes = h.get_full_node_names()
    paths = h.get_friendly_paths()
    assert paths == [
        ['column[source.age]', 'column[target.john_average]'],
        ['column[source.age]', 'column[target.john_total]'],
        ['column[source.age]', 'column[target.mary_average]'],
        ['column[source.age]', 'column[target.mary_total]']
    ]
    # TODO: the agg functions used inside the pivot are currently not extracted.
