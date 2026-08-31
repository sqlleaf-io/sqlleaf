from __future__ import annotations

"""
Quick tests for the custom PL/pgSQL-like dialect implemented in plpgsql.py.

Run directly:
    python test_plpgsql.py
"""

from sqlglot import parse_one

from plpgsql import PLpgSQL, Perform


def test_perform_function_call() -> None:
    tree = parse_one("PERFORM my_function()", dialect=PLpgSQL)
    assert isinstance(tree, Perform), f"Expected Perform, got {type(tree)}"

    exprs = tree.args.get("expressions")
    assert exprs and len(exprs) == 1, "Perform should have a single projection expression"

    sql = tree.sql(dialect=PLpgSQL)
    # Postgres generator normalizes function names to UPPER by default
    assert sql == "PERFORM MY_FUNCTION()", f"Unexpected SQL: {sql}"


def test_perform_select_like_tail() -> None:
    # PERFORM should support all SELECT trailing clauses without the SELECT keyword
    tree = parse_one("PERFORM 1 FROM t WHERE id = 42", dialect=PLpgSQL)
    assert isinstance(tree, Perform), f"Expected Perform, got {type(tree)}"

    sql = tree.sql(dialect=PLpgSQL)
    assert sql == "PERFORM 1 FROM t WHERE id = 42", f"Unexpected SQL: {sql}"


if __name__ == "__main__":
    # Run the tests sequentially and print a simple success message
    test_perform_function_call()
    test_perform_select_like_tail()
    print("All PLpgSQL tests passed.")
