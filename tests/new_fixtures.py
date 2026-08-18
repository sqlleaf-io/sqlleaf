import os
import sys
import typing as t

import pytest

from sqlleaf.models.query import Q, Query, QueryHolder
from sqlleaf.models.query.table import TableQuery
from sqlleaf.processors.collector.collector import CollectQueryResult

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import logging

from sqlglot import exp

import sqlleaf

logging.basicConfig(level=logging.NOTSET)
logger = logging.getLogger("sqlleaf")
logger.setLevel(logging.DEBUG)


class LineageHolderDummy:
    def __init__(self):
        self.lineage = sqlleaf.Lineage()

    def generate(self, sql: str, dialect: str):
        self.lineage.generate(sql=sql, dialect=dialect)

        self._all_nodes = self.lineage.get_nodes()
        self._all_edges = self.lineage.get_edges()
        self._all_paths = list(self.lineage.get_paths())
        self._collected_queries = self.lineage.collected_queries

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
    def queries_original(self) -> t.List[Q]:
        return [h.original for h in self.holders]

    @property
    def queries_transformed(self) -> list[Query | None]:
        return [h.transformed for h in self.holders]

    @property
    def holders(self) -> t.List[QueryHolder]:
        new_holders = []
        for holder in self.lineage.collected_queries.queries:
            query = holder.original
            if not (
                isinstance(query, TableQuery)
                and exp.table_name(query.get_target_as_table()).lower()
                in ["test_source", "fruit.raw", "fruit.processed"]
            ):
                new_holders.append(holder)
        return new_holders

    @property
    def paths(self) -> t.List[str]:
        paths = []
        for path in self._all_paths:
            paths.append([hop.friendly_name for hop in path.node_hops()])
        return paths

    @property
    def paths_full(self) -> t.List[str]:
        paths = []
        for path in self._all_paths:
            paths.append([hop.full_name for hop in path.node_hops()])
        return paths

    @property
    def collected_queries(self) -> CollectQueryResult | None:
        return self._collected_queries

    @property
    def query_types(self) -> t.List:
        types = [type(h.original) for h in self.holders]
        return types


@pytest.fixture(scope="function")
def holder():
    def _create_holder(sql: str, dialect: str, with_tables: bool = False, hooks: dict | None = None) -> LineageHolderDummy:
        h = LineageHolderDummy()
        if hooks:
            h.lineage.register_hooks(hooks)
        if with_tables:
            h.generate(sql=COMMON_TABLES, dialect=dialect)
        h.generate(sql=sql, dialect=dialect)
        return h

    return _create_holder


def to_sql(expressions: t.List[exp.Expr], dialect: str) -> t.List[str]:
    return [e.sql(dialect=dialect) for e in expressions]


def assert_query_does_nothing(h: LineageHolderDummy):
    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.edges) == 0


COMMON_TABLES = """
CREATE TABLE test_source (name VARCHAR);

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
