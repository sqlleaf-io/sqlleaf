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
            arow RECORD;
        BEGIN
            PERFORM 1;
        END;
        """
        tree = parse_one(sql, dialect=PLpgSQL)
        self.assertIsInstance(tree, PLBlock)

        decl = tree.args.get("declare")
        self.assertIsInstance(decl, exp.Declare)

        items = list(decl.expressions)

        first0 = items[0].this[0]
        self.assertEqual(first0.name, "my_id")
        self.assertIn(items[0].args.get("kind").sql(), {"INT"})
        self.assertIsNone(items[0].args.get("default").to_py(), None)

        first1 = items[1].this[0]
        self.assertEqual(first1.name, "my_count")
        self.assertIn(items[1].args.get("kind").sql(), {"INTEGER"})
        self.assertEqual(items[1].args.get("default").to_py(), 0)

        first2 = items[2].this[0]
        self.assertEqual(first2.name, "arow")
        self.assertIn(items[2].args.get("kind").sql(), {"RECORD"})
        self.assertEqual(items[2].args.get("default").to_py(), None)

        out = tree.sql(dialect=PLpgSQL)


    def test_declare_row_and_column_type(self) -> None:
        sql = """
        DECLARE
            myrow tablename%ROWTYPE;
            myfield tablename.columnname%TYPE;
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

        # First is a table row type
        first = items[0]
        # Ensure helper exists and returns True
        self.assertTrue(hasattr(first, "is_row_type"))
        self.assertTrue(first.is_row_type())

        # Second is a column type
        second = items[1]
        self.assertTrue(hasattr(second, "is_column_type"))
        self.assertTrue(second.is_column_type())

        # Round-trip contains the PL/pgSQL markers
        rendered = tree.sql(dialect=PLpgSQL)
        self.assertIn("%ROWTYPE", rendered)
        self.assertIn("%TYPE", rendered)

    def test_declare_alias_for_param(self) -> None:
        sql = """
        DECLARE
            arg1 ALIAS FOR $1;
        BEGIN
            PERFORM 1;
        END;
        """
        tree = parse_one(sql, dialect=PLpgSQL)
        self.assertIsInstance(tree, PLBlock)

        decl = tree.args.get("declare")
        self.assertIsInstance(decl, exp.Declare)

        items = list(decl.expressions)
        self.assertEqual(len(items), 1)

        item = items[0]
        # Ensure it is our extended declare item
        from plpgsql import PLDeclareItem  # local import to avoid circular during typing
        self.assertIsInstance(item, PLDeclareItem)

        # Name should be arg1
        self.assertEqual(item.this[0].name, "arg1")

        # alias_for must be present and be an exp.Var representing $1
        alias_for = item.args.get("alias_for")
        self.assertIsInstance(alias_for, exp.Var)
        # .name property renders the identifier
        self.assertEqual(alias_for.name, "$1")

        # Round-trip keeps the alias syntax
        rendered = tree.sql(dialect=PLpgSQL)
        self.assertIn("ALIAS FOR $1", rendered)


if __name__ == "__main__":
    unittest.main()
