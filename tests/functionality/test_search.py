import inspect
import os
import sys

from sqlleaf.models.node import ColumnNode, LiteralNode
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"

SQL = """
CREATE TABLE fruit.source (price INT, qty INT);
CREATE TABLE fruit.target (total INT, other INT);
INSERT INTO fruit.target (total, other)
SELECT SUM(price), SUM(qty) + 1
FROM fruit.source;
"""


SAME_NAME_SQL = """
CREATE TABLE fruit.raw (price INT);
CREATE TABLE veg.raw (price INT);
CREATE TABLE fruit.summary (total INT);
CREATE TABLE veg.summary (total INT);
INSERT INTO fruit.summary (total) SELECT price FROM fruit.raw;
INSERT INTO veg.summary (total) SELECT price FROM veg.raw;
"""


def _column(h, name):
    return h.lineage.find_nodes(ColumnNode(column=name))[0]


def test__paths_downstream_from_starts_at_node(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    price = _column(h, "price")
    paths = list(h.lineage.paths_downstream_from(price))

    assert len(paths) == 1
    assert all(p.node_hops()[0].full_name == price.full_name for p in paths)
    assert [n.friendly_name for n in paths[0].node_hops()] == [
        "column[fruit.source.price]",
        "function[SUM]",
        "column[fruit.target.total]",
    ]


def test__paths_downstream_from_follows_multiple_hops(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    qty = _column(h, "qty")
    paths = list(h.lineage.paths_downstream_from(qty))

    assert len(paths) == 1
    assert paths[0].length == 3
    assert [n.friendly_name for n in paths[0].node_hops()] == [
        "column[fruit.source.qty]",
        "function[SUM]",
        "function[ADD]",
        "column[fruit.target.other]",
    ]


def test__paths_downstream_from_excludes_paths_from_other_nodes(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    price_paths = list(h.lineage.paths_downstream_from(_column(h, "price")))

    assert all(p.node_hops()[0].get_name() == "price" for p in price_paths)
    assert all("column[fruit.source.qty]" not in {n.friendly_name for n in p.node_hops()} for p in price_paths)


def test__paths_downstream_from_leaf_node_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert list(h.lineage.paths_downstream_from(_column(h, "total"))) == []
    assert list(h.lineage.paths_downstream_from(_column(h, "other"))) == []


def test__paths_downstream_from_node_not_in_graph_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert list(h.lineage.paths_downstream_from(ColumnNode(schema="fruit", table="missing", column="x"))) == []


def test__paths_upstream_from_ends_at_node(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    total = _column(h, "total")
    paths = list(h.lineage.paths_upstream_from(total))

    assert len(paths) == 1
    assert all(p.node_hops()[-1].full_name == total.full_name for p in paths)
    assert [n.friendly_name for n in paths[0].node_hops()] == [
        "column[fruit.source.price]",
        "function[SUM]",
        "column[fruit.target.total]",
    ]


def test__paths_upstream_from_follows_multiple_hops(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_upstream_from(_column(h, "other")))
    hop_names = sorted([n.friendly_name for n in p.node_hops()] for p in paths)

    assert len(paths) == 2
    assert hop_names == [
        ["column[fruit.source.qty]", "function[SUM]", "function[ADD]", "column[fruit.target.other]"],
        ["literal[1]", "function[ADD]", "column[fruit.target.other]"],
    ]


def test__paths_upstream_from_root_node_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert list(h.lineage.paths_upstream_from(_column(h, "price"))) == []
    assert list(h.lineage.paths_upstream_from(_column(h, "qty"))) == []


def test__paths_upstream_from_node_not_in_graph_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert list(h.lineage.paths_upstream_from(ColumnNode(schema="fruit", table="missing", column="x"))) == []


def test__paths_upstream_from_does_not_modify_graph(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    nodes_before = set(h.lineage.graph.nodes)
    edges_before = set(h.lineage.graph.edges(keys=True))

    list(h.lineage.paths_upstream_from(_column(h, "other")))

    assert set(h.lineage.graph.nodes) == nodes_before
    assert set(h.lineage.graph.edges(keys=True)) == edges_before


def test__paths_downstream_and_upstream_return_generators(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert inspect.isgenerator(h.lineage.paths_downstream_from(_column(h, "price")))
    assert inspect.isgenerator(h.lineage.paths_upstream_from(_column(h, "total")))


def test__has_path_between_connected_columns_returns_true(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.lineage.has_path(ColumnNode(column="price"), ColumnNode(column="total")) is True


def test__has_path_follows_multiple_hops(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.lineage.has_path(ColumnNode(column="qty"), ColumnNode(column="other")) is True


def test__has_path_from_literal_to_column_returns_true(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    one = [n for n in h.lineage.find_nodes(LiteralNode()) if n.get_name() == "1"][0]

    assert h.lineage.has_path(one, ColumnNode(column="other")) is True


def test__has_path_is_directional(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.lineage.has_path(ColumnNode(column="total"), ColumnNode(column="price")) is False


def test__has_path_unconnected_columns_returns_false(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert h.lineage.has_path(ColumnNode(column="price"), ColumnNode(column="other")) is False


def test__has_path_node_not_in_graph_returns_false(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    missing = ColumnNode(schema="fruit", table="missing", column="x")

    assert h.lineage.has_path(missing, ColumnNode(column="total")) is False
    assert h.lineage.has_path(ColumnNode(column="price"), missing) is False


def test__has_path_matches_any_node_with_same_name(holder):
    sql = """
    CREATE TABLE fruit.source (price INT, qty INT);
    CREATE TABLE veg.raw (price INT, weight INT);
    CREATE TABLE fruit.target (total INT, other INT);
    INSERT INTO fruit.target (total, other)
    SELECT f.price, v.weight
    FROM fruit.source AS f
    CROSS JOIN veg.raw AS v;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.lineage.has_path(ColumnNode(column="price"), ColumnNode(column="total")) is True
    assert h.lineage.has_path(ColumnNode(column="weight"), ColumnNode(column="total")) is False


def test__paths_between_nodes_returns_paths_from_src_to_dst(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_between_nodes(ColumnNode(column="price"), ColumnNode(column="total")))

    assert len(paths) == 1
    assert [n.friendly_name for n in paths[0].node_hops()] == [
        "column[fruit.source.price]",
        "function[SUM]",
        "column[fruit.target.total]",
    ]


def test__paths_between_nodes_follows_multiple_hops(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_between_nodes(ColumnNode(column="qty"), ColumnNode(column="other")))

    assert len(paths) == 1
    assert paths[0].length == 3
    assert [n.friendly_name for n in paths[0].node_hops()] == [
        "column[fruit.source.qty]",
        "function[SUM]",
        "function[ADD]",
        "column[fruit.target.other]",
    ]


def test__paths_between_nodes_excludes_paths_from_other_sources(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_between_nodes(ColumnNode(column="qty"), ColumnNode(column="other")))

    assert all(p.node_hops()[0].full_name == _column(h, "qty").full_name for p in paths)
    assert all("literal[1]" not in {n.friendly_name for n in p.node_hops()} for p in paths)


def test__paths_between_nodes_without_connection_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert list(h.lineage.paths_between_nodes(ColumnNode(column="price"), ColumnNode(column="other"))) == []
    assert list(h.lineage.paths_between_nodes(ColumnNode(column="qty"), ColumnNode(column="total"))) == []


def test__paths_between_nodes_node_not_in_graph_returns_empty(holder):
    h = holder(sql=SQL, dialect=DIALECT)
    missing = ColumnNode(schema="fruit", table="missing", column="x")

    assert list(h.lineage.paths_between_nodes(missing, ColumnNode(column="total"))) == []
    assert list(h.lineage.paths_between_nodes(ColumnNode(column="price"), missing)) == []


def test__paths_between_nodes_returns_generator(holder):
    h = holder(sql=SQL, dialect=DIALECT)

    assert inspect.isgenerator(h.lineage.paths_between_nodes(ColumnNode(column="price"), ColumnNode(column="total")))


def test__paths_downstream_from_partial_node_matches_all_same_named_nodes(holder):
    h = holder(sql=SAME_NAME_SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_downstream_from(ColumnNode(column="price")))

    assert len(paths) == 2
    assert {p.node_hops()[0].friendly_name for p in paths} == {"column[fruit.raw.price]", "column[veg.raw.price]"}


def test__paths_upstream_from_partial_node_matches_all_same_named_nodes(holder):
    h = holder(sql=SAME_NAME_SQL, dialect=DIALECT)
    paths = list(h.lineage.paths_upstream_from(ColumnNode(column="total")))

    assert len(paths) == 2
    assert {p.node_hops()[0].friendly_name for p in paths} == {"column[fruit.raw.price]", "column[veg.raw.price]"}
    assert {p.node_hops()[-1].friendly_name for p in paths} == {"column[fruit.summary.total]", "column[veg.summary.total]"}
