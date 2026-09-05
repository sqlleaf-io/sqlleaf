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

    def test_plpgsql_declare_alias_for_parameter(self) -> None:
        sql = """
        DECLARE
            subtotal ALIAS FOR $1;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(out, 'DECLARE subtotal ALIAS FOR $1; BEGIN SELECT 1; END')

    def test_exception_single_when_single_stmt(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exception_multiple_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN unique_violation THEN RAISE; WHEN division_by_zero THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exception_when_multiple_conditions(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN unique_violation OR division_by_zero THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exception_when_sqlstate(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN SQLSTATE '22012' THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_declare_body_and_exception(self) -> None:
        sql = (
            "DECLARE a INTEGER; BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RAISE; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(
            expr.sql(dialect=plpgsql),
            "DECLARE a INTEGER; BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RAISE; END",
        )

    def test_exception_requires_when(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION END;", dialect=plpgsql)

    def test_when_requires_condition(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION WHEN THEN RAISE; END;", dialect=plpgsql)

    def test_when_requires_statement(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION WHEN division_by_zero THEN END;", dialect=plpgsql)
