import sys
import os
import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import logging


logging.basicConfig(level=logging.NOTSET)

logger = logging.getLogger("sqlleaf")
logger.setLevel(logging.DEBUG)

import sqlleaf
from sqlleaf import structs
from sqlglot import exp

DIALECT = 'postgres'

class LineageDummy(sqlleaf.Lineage):

    def get_full_node_names(self):
        return [n.full_name for n in self.get_nodes()]

    def get_friendly_node_names(self):
        return [n.friendly_name for n in self.get_nodes()]

    def get_friendly_paths(self):
        paths = []
        for path in self.get_paths():
            paths.append([hop.friendly_name for hop in path.node_hops()])
        return paths

    def get_queries_created(self):
        all_queries = self.get_queries()
        new_queries = []
        for query in all_queries:
            # Remove the COMMON_TABLES queries
            if not (isinstance(query, structs.TableQuery) and exp.table_name(query.child_table) in ['fruit.raw', 'fruit.processed']):
                new_queries.append(query)
        return new_queries


@pytest.fixture
def holder():
    def _create_holder(with_tables: bool = False):
        h = LineageDummy()
        if with_tables:
            h.generate(COMMON_TABLES, dialect=DIALECT)
        return h
    return _create_holder


def is_subset(subarr, arr):
    """
    Check if an array is a subset of another array.
    """
    missing = [s for s in subarr if s not in arr]
    return len(missing) == 0


COMMON_TABLES = '''
 CREATE TABLE fruit.raw
 (
     name VARCHAR,
     kind VARCHAR,
     age  INT,
     jsonblob JSONB
 );

 CREATE TABLE fruit.processed
 (
     name        VARCHAR,
     kind        VARCHAR,
     age         INT,
     kind_with_x TEXT GENERATED ALWAYS AS (
         kind || 'x'
         ) STORED,
     label       VARCHAR,
     amount      INT,
     number      INT,
     created_at  timestamp,
     updated_at  timestamp,
     inserted_at date,
     name1       VARCHAR,
     name2       VARCHAR,
     name3       VARCHAR,
     name4       VARCHAR,
     name5       VARCHAR,
     jsonblob    JSONB
 );

 '''
