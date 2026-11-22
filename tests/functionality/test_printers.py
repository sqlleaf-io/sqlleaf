import json
import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"

SQL = """
CREATE TABLE fruit.raw (price INT, qty INT);
CREATE TABLE fruit.summary (total INT, other INT);
INSERT INTO fruit.summary (total, other)
SELECT SUM(price), SUM(qty) + 1
FROM fruit.raw;
"""


def test__print_json_outputs_all_sections(holder, capsys):
    h = holder(sql=SQL, dialect=DIALECT)
    h.lineage.print_json()
    data = json.loads(capsys.readouterr().out)

    assert set(data.keys()) == {"node", "edges", "queries", "paths"}


def test__print_json_matches_lineage_contents(holder, capsys):
    h = holder(sql=SQL, dialect=DIALECT)
    h.lineage.print_json()
    data = json.loads(capsys.readouterr().out)

    assert len(data["node"]) == len(h.lineage.get_nodes())
    assert len(data["edges"]) == len(h.lineage.get_edges())
    assert len(data["queries"]) == len(h.lineage.get_original_queries())
    assert len(data["paths"]) == len(list(h.lineage.get_paths()))
    assert {p["id"] for p in data["paths"]} == {p.id for p in h.lineage.get_paths()}


def test__print_tree_shows_friendly_names(holder, capsys):
    h = holder(sql=SQL, dialect=DIALECT)
    h.lineage.print_tree()
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        ".",
        "├── column[fruit.summary.total]",
        "│   └── function[SUM]",
        "│       └── column[fruit.raw.price]",
        "└── column[fruit.summary.other]",
        "    └── function[ADD]",
        "        ├── function[SUM]",
        "        │   └── column[fruit.raw.qty]",
        "        └── literal[1]",
    ]


def test__print_tree_full_name_shows_full_names(holder, capsys):
    h = holder(sql=SQL, dialect=DIALECT)
    h.lineage.print_tree(full_name=True)
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        ".",
        "├── column[name=total type=INT properties=[kind=table table=summary schema=fruit]]",
        "│   └── function[name=SUM type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "│       └── column[name=price type=INT properties=[kind=table table=raw schema=fruit]]",
        "└── column[name=other type=INT properties=[kind=table table=summary schema=fruit]]",
        "    └── function[name=ADD type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=1 func_depth=0 func_arg=0]]",
        "        ├── function[name=SUM type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=1 func_depth=1 func_arg=0]]",
        "        │   └── column[name=qty type=INT properties=[kind=table table=raw schema=fruit]]",
        "        └── literal[name=1 type=INT position=[query_depth=0 query_width=0 statement=2 select=1 func_depth=1 func_arg=1]]",
    ]




def test__print_tree_uses_branch_connector_for_each_non_final_child(holder, capsys):
    sql = """
    CREATE TABLE fruit.raw (price INT, qty INT);
    CREATE TABLE fruit.summary (total INT);
    INSERT INTO fruit.summary (total)
    SELECT COALESCE(price, qty, 0)
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)
    h.lineage.print_tree()
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        ".",
        "└── column[fruit.summary.total]",
        "    └── function[COALESCE]",
        "        ├── column[fruit.raw.price]",
        "        ├── column[fruit.raw.qty]",
        "        └── literal[0]",
    ]


def test__print_tree_nested_function_connectors_per_level(holder, capsys):
    sql = """
    CREATE TABLE fruit.raw (price INT, qty INT);
    CREATE TABLE fruit.summary (total INT);
    INSERT INTO fruit.summary (total)
    SELECT price + qty + 1
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)
    h.lineage.print_tree()
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        ".",
        "└── column[fruit.summary.total]",
        "    └── function[ADD]",
        "        ├── function[ADD]",
        "        │   ├── column[fruit.raw.price]",
        "        │   └── column[fruit.raw.qty]",
        "        └── literal[1]",
    ]


def test__print_tree_single_child_uses_corner_connector(holder, capsys):
    sql = """
    CREATE TABLE fruit.raw (price INT);
    CREATE TABLE fruit.summary (total INT);
    INSERT INTO fruit.summary (total) SELECT price FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)
    h.lineage.print_tree()
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        ".",
        "└── column[fruit.summary.total]",
        "    └── column[fruit.raw.price]",
    ]


def test__print_paths_outputs_one_line_per_path(holder, capsys):
    h = holder(sql=SQL, dialect=DIALECT)
    h.lineage.print_paths()
    lines = capsys.readouterr().out.splitlines()

    assert lines == [
        "column[fruit.raw.price] -> function[SUM] -> column[fruit.summary.total]",
        "column[fruit.raw.qty] -> function[SUM] -> function[ADD] -> column[fruit.summary.other]",
        "literal[1] -> function[ADD] -> column[fruit.summary.other]",
    ]
