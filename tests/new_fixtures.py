import sys
import os
import pytest

from sqlleaf.objects.query_types import TableQuery

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

import logging

logging.basicConfig(level=logging.NOTSET)
logger = logging.getLogger("sqlleaf")
logger.setLevel(logging.DEBUG)

import sqlleaf

from sqlglot import exp


class LineageHolderDummy:
    def __init__(self):
        self.lineage = sqlleaf.Lineage()

    def generate(self, sql: str, dialect: str):
        self.lineage.generate(sql=sql, dialect=dialect)

        self._all_nodes = self.lineage.get_nodes()
        self._all_edges = self.lineage.get_edges()
        self._all_paths = list(self.lineage.get_paths())
        self._all_queries = self.lineage.get_queries()

    @property
    def nodes(self):
        return [n.friendly_name for n in self._all_nodes]

    @property
    def nodes_full(self):
        return [n.full_name for n in self._all_nodes]

    @property
    def edges(self):
        return self._all_edges

    @property
    def queries(self):
        new_queries = []
        for query in self._all_queries:
            # Remove the COMMON_TABLES queries
            if not (isinstance(query, TableQuery) and exp.table_name(query.child_table).lower() in ["fruit.raw", "fruit.processed"]):
                new_queries.append(query)
        return new_queries

    @property
    def paths(self):
        paths = []
        for path in self._all_paths:
            paths.append([hop.friendly_name for hop in path.node_hops()])
        return paths

    @property
    def paths_full(self):
        paths = []
        for path in self._all_paths:
            paths.append([hop.full_name for hop in path.node_hops()])
        return paths


@pytest.fixture(scope="function")
def holder():
    def _create_holder(sql: str, dialect: str, with_tables: bool = False):
        h = LineageHolderDummy()
        if with_tables:
            h.generate(sql=COMMON_TABLES, dialect=dialect)
        h.generate(sql=sql, dialect=dialect)
        return h

    return _create_holder


def is_subset(subarr, arr):
    """
    Check if an array is a subset of another array.
    """
    missing = [s for s in subarr if s not in arr]
    return len(missing) == 0


COMMON_TABLES = """
 CREATE TABLE fruit.raw
 (
     name VARCHAR,
     kind VARCHAR,
     age  INT,
     color VARCHAR,
     jsonblob JSONB
 );

 CREATE TABLE fruit.processed
 (
     name        VARCHAR,
     kind        VARCHAR,
     age         INT,
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

 """
