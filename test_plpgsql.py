from __future__ import annotations

"""
Unittest-based tests for the custom PL/pgSQL-like dialect implemented in plpgsql.py.

Run directly:
    python -m unittest test_plpgsql.py
"""

import unittest

from sqlglot import parse_one
from sqlglot.errors import ParseError

from plpgsql import PLpgSQL, Perform


class TestPLpgSQL(unittest.TestCase):
    def test_perform_function_call(self) -> None:
        tree = parse_one("PERFORM my_function()", dialect=PLpgSQL)
        self.assertIsInstance(tree, Perform, f"Expected Perform, got {type(tree)}")

        exprs = tree.args.get("expressions")
        self.assertIsNotNone(exprs, "Perform should have a projection expression list")
        self.assertEqual(len(exprs), 1, "Perform should have a single projection expression")

        sql = tree.sql(dialect=PLpgSQL)
        # Postgres generator normalizes function names to UPPER by default
        self.assertEqual(sql, "PERFORM MY_FUNCTION()", f"Unexpected SQL: {sql}")

    def test_perform_select_like_tail(self) -> None:
        # PERFORM should support all SELECT trailing clauses without the SELECT keyword
        tree = parse_one("PERFORM 1 FROM t WHERE id = 42", dialect=PLpgSQL)
        self.assertIsInstance(tree, Perform, f"Expected Perform, got {type(tree)}")

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(sql, "PERFORM 1 FROM t WHERE id = 42", f"Unexpected SQL: {sql}")

    def test_begin_perform(self) -> None:
        tree = parse_one("BEGIN PERFORM 1 FROM t WHERE id = 42; END;", dialect=PLpgSQL)

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(sql, "BEGIN PERFORM 1 FROM t WHERE id = 42; END", f"Unexpected SQL: {sql}")

    def test_begin_perform_twice(self) -> None:
        tree = parse_one("BEGIN SELECT 1 INTO var1; SELECT 2 INTO var2; END;", dialect=PLpgSQL)

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(
            sql,
            "BEGIN SELECT 1 INTO var1; SELECT 2 INTO var2; END;",
            f"Unexpected SQL: {sql}",
        )

    def test_begin_empty_raises(self) -> None:
        with self.assertRaises(ParseError) as cm:
            parse_one("BEGIN END;", dialect=PLpgSQL)

        self.assertEqual(str(cm.exception), "Empty BEGIN ... END block is not allowed")


if __name__ == "__main__":
    unittest.main()
