import os
import sys

from sqlleaf.models.node import ColumnNode, FunctionNode, LiteralNode
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"

SCHEMA_SQL = """
CREATE TABLE fruit.raw (price INT, qty INT);
CREATE TABLE fruit.summary (total INT, other INT);
CREATE TABLE fruit.other (id INT);
"""

SQL = """
INSERT INTO fruit.summary (total, other)
SELECT SUM(price), SUM(qty) + 1
FROM fruit.raw;
"""

FULL_SQL = SCHEMA_SQL + SQL


def test__find_nodes_by_class_returns_all_occurrences(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    sums = h.lineage.find_nodes(FunctionNode())
    names = [n.get_name() for n in sums]

    assert names.count("SUM") == 2
    assert all(isinstance(n, FunctionNode) for n in sums)
    assert len({n.full_name for n in sums}) == len(sums)


def test__find_nodes_by_class_returns_only_that_class(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    literals = h.lineage.find_nodes(LiteralNode())

    assert len(literals) > 0
    assert all(type(n) is LiteralNode for n in literals)


def test__find_nodes_column_by_name_returns_matching_column(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    totals = h.lineage.find_nodes(ColumnNode(column="total"))

    assert len(totals) == 1
    assert all(isinstance(n, ColumnNode) for n in totals)
    assert totals[0].friendly_name == "column[fruit.summary.total]"


def test__find_nodes_literal_by_class_returns_literal_values(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    literals = h.lineage.find_nodes(LiteralNode())

    assert all(isinstance(n, LiteralNode) for n in literals)
    assert "1" in {n.get_name() for n in literals}


def test__find_nodes_unknown_name_returns_empty(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)

    assert h.lineage.find_nodes(FunctionNode(name="NOT_A_FUNCTION")) == []


def test__find_nodes_without_arguments_returns_empty(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)

    assert h.lineage.find_nodes() == []


def test__find_nodes_multiple_queries_are_ored_without_duplicates(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    combined = h.lineage.find_nodes(FunctionNode(), FunctionNode(name="SUM"), FunctionNode(name="sum"))
    by_class = h.lineage.find_nodes(FunctionNode())

    assert len(combined) == len(by_class)
    assert {n.full_name for n in combined} == {n.full_name for n in by_class}


def test__node_index_tracks_every_graph_node(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    graph_nodes = [data["attrs"] for _, data in h.lineage.graph.nodes(data=True)]
    indexed = {n.full_name for cls in {type(n) for n in graph_nodes} for n in h.lineage.object_mapping.node_index.get(cls)}

    assert indexed == {n.full_name for n in graph_nodes}


def test__find_nodes_reflects_second_generate(holder):
    h = holder(sql=FULL_SQL, dialect=DIALECT)
    assert len(h.lineage.find_nodes(FunctionNode(name="SUM"))) == 2

    h.generate(sql="INSERT INTO fruit.other (id) SELECT MAX(id) FROM fruit.other;", dialect=DIALECT, on_error="stop")

    assert len(h.lineage.find_nodes(FunctionNode(name="SUM"))) == 2
    assert len(h.lineage.find_nodes(FunctionNode(name="MAX"))) == 1


def test__find_nodes_column_name_matches_same_name_in_different_tables(holder):
    sql = """
    CREATE TABLE fruit.raw (price INT, qty INT);
    CREATE TABLE veg.raw (price INT, weight INT);
    CREATE TABLE fruit.summary (total INT, other INT);
    INSERT INTO fruit.summary (total, other)
    SELECT f.price, v.price
    FROM fruit.raw AS f
    CROSS JOIN veg.raw AS v;
    """
    h = holder(sql=sql, dialect=DIALECT)
    prices = h.lineage.find_nodes(ColumnNode(column="price"))

    assert all(isinstance(n, ColumnNode) for n in prices)
    assert len(prices) == 2
    assert {n.friendly_name for n in prices} == {"column[fruit.raw.price]", "column[veg.raw.price]"}
