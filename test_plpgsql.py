import unittest

import sqlglot
from plpgsql import plpgsql, PGBlock


class TestPlPgSQL(unittest.TestCase):
    def test_begin_end_roundtrip(self) -> None:
        sql = "BEGIN END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_begin_select_one(self) -> None:
        sql = "BEGIN SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_begin_select_two(self) -> None:
        sql = "BEGIN SELECT 1; SELECT 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_declare_defaults_to_null(self) -> None:
        sql = """
        DECLARE
            my_id INTEGER;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE my_id INTEGER; BEGIN SELECT 1; END")

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        # Identifier name
        self.assertEqual(item.this.name, "my_id")
        # Has a type expression and no initializer
        self.assertIsNotNone(item.args.get("kind"))
        self.assertIsNone(item.args.get("expression"))

    def test_plpgsql_declare_colon_equals(self) -> None:
        sql = """
        DECLARE
            my_count INTEGER := 0;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE my_count INTEGER := 0; BEGIN SELECT 1; END")

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        self.assertEqual(item.this.name, "my_count")
        self.assertIsNotNone(item.args.get("kind"))
        self.assertIsNotNone(item.args.get("expression"))


    def test_plpgsql_declare_equals(self) -> None:
        sql = """
        DECLARE
            my_count INTEGER = 0;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE my_count INTEGER = 0; BEGIN SELECT 1; END")

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        self.assertEqual(item.this.name, "my_count")
        self.assertIsNotNone(item.args.get("kind"))
        self.assertIsNotNone(item.args.get("expression"))

    # TODO:
    #  myrow tablename%ROWTYPE;
    #  myfield tablename.columnname%TYPE;

    def test_plpgsql_declare_default(self) -> None:
        sql = """
        DECLARE
            my_count INTEGER DEFAULT 32;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE my_count INTEGER DEFAULT 32; BEGIN SELECT 1; END")

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        self.assertEqual(item.this.name, "my_count")
        self.assertIsNotNone(item.args.get("kind"))
        self.assertIsNotNone(item.args.get("expression"))


    def test_plpgsql_declare_record(self) -> None:
        sql = """
        DECLARE
            my_count RECORD;
            quantity numeric(5);
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE my_count RECORD; quantity NUMERIC(5); BEGIN SELECT 1; END")

    def test_plpgsql_declare_constant(self) -> None:
        sql = """
        DECLARE
            amount CONSTANT integer := 5;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, "DECLARE amount CONSTANT INTEGER := 5; BEGIN SELECT 1; END")

    def test_plpgsql_declare_collate(self) -> None:
        sql = """
        DECLARE
            local_a text COLLATE "en_US";
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, 'DECLARE local_a TEXT COLLATE "en_US"; BEGIN SELECT 1; END')

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        self.assertEqual(item.this.name, "local_a")
        self.assertIsNotNone(item.args.get("kind"))
        self.assertIsNone(item.args.get("expression"))
        self.assertIsNotNone(item.args.get("collate"))

    def test_plpgsql_declare_collate_not_null_default(self) -> None:
        sql = """
        DECLARE
            local_b text COLLATE "en_US" NOT NULL DEFAULT 'x';
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, 'DECLARE local_b TEXT COLLATE "en_US" NOT NULL DEFAULT \'x\'; BEGIN SELECT 1; END')

        # Structure checks
        self.assertIsInstance(expr, PGBlock)
        self.assertIsNotNone(expr.args.get("declare"))
        decl = expr.args["declare"]
        self.assertEqual(len(list(decl.expressions)), 1)
        item = decl.expressions[0]
        self.assertEqual(item.this.name, "local_b")
        self.assertIsNotNone(item.args.get("kind"))
        self.assertTrue(item.args.get("not_null"))
        self.assertTrue(item.args.get("default"))
        self.assertIsNotNone(item.args.get("expression"))
        self.assertIsNotNone(item.args.get("collate"))
