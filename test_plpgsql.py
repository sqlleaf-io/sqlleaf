from __future__ import annotations

"""
Unittest-based tests for the custom PL/pgSQL-like dialect implemented in plpgsql.py.

Run directly:
    python -m unittest test_plpgsql.py
"""

import unittest

from sqlglot.errors import ParseError
from sqlglot import exp, parse_one
from plpgsql import PLBlock

from plpgsql import PLpgSQL, Perform


class TestPLpgSQL(unittest.TestCase):
    def test_perform_function_call(self) -> None:
        query = "PERFORM my_function()"
        tree = parse_one(query, dialect=PLpgSQL)
        self.assertIsInstance(tree, Perform, f"Expected Perform, got {type(tree)}")

        exprs = tree.args.get("expressions")
        self.assertIsNotNone(exprs, "Perform should have a projection expression list")
        self.assertEqual(len(exprs), 1, "Perform should have a single projection expression")

        sql = tree.sql(dialect=PLpgSQL)
        # Postgres generator normalizes function names to UPPER by default
        self.assertEqual(sql, "PERFORM MY_FUNCTION()", f"Unexpected SQL: {sql}")

    def test_perform_with_where(self) -> None:
        query = "PERFORM 1 FROM t WHERE id = 42"
        # PERFORM should support all SELECT trailing clauses without the SELECT keyword
        tree = parse_one(query, dialect=PLpgSQL)
        self.assertIsInstance(tree, Perform, f"Expected Perform, got {type(tree)}")

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(sql, query, f"Unexpected SQL: {sql}")

    def test_begin_perform(self) -> None:
        query = "BEGIN PERFORM 1 FROM t WHERE id = 42; END"
        tree = parse_one(query, dialect=PLpgSQL)

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(sql, query, f"Unexpected SQL: {sql}")

    def test_begin_perform_twice(self) -> None:
        query = "BEGIN SELECT 1 INTO var1; SELECT 2 INTO var2; END;"
        tree = parse_one(query, dialect=PLpgSQL)

        sql = tree.sql(dialect=PLpgSQL)
        self.assertEqual(
            sql,
            query,
            f"Unexpected SQL: {sql}",
        )

    def test_begin_empty_raises(self) -> None:
        with self.assertRaises(ParseError) as cm:
            parse_one("BEGIN END;", dialect=PLpgSQL)

        self.assertEqual(str(cm.exception), "Empty BEGIN ... END block is not allowed")


class TestPLpgSQLDeclare(unittest.TestCase):
    def test_declare_before_begin(self) -> None:
        sql = """
        DECLARE
            my_id INTEGER;
            my_count INTEGER := 0;
        BEGIN
            PERFORM 1;
        END;
        """
        tree = parse_one(sql, dialect=PLpgSQL)
        self.assertIsInstance(tree, PLBlock)

        decl = tree.args.get("declare")
        self.assertIsInstance(decl, exp.Declare)

        items = list(decl.expressions)
        self.assertEqual(len(items), 2)

        first0 = items[0].this[0]
        self.assertEqual(first0.name, "my_id")
        self.assertIn(items[0].args.get("kind").sql(), {"INT"})
        self.assertIsNone(items[0].args.get("default").to_py(), None)

        first1 = items[1].this[0]
        self.assertEqual(first1.name, "my_count")
        self.assertIn(items[1].args.get("kind").sql(), {"INTEGER"})
        self.assertEqual(items[1].args.get("default").to_py(), 0)

        out = tree.sql(dialect=PLpgSQL)


if __name__ == "__main__":
    unittest.main()
