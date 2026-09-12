import unittest

import sqlglot
from plpgsql.p_dialect import plpgsql
from plpgsql.classes import *


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

    def test_begin_variable_assignment(self) -> None:
        sql = "BEGIN x := 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_begin_variable_equals_fails(self) -> None:
        sql = "BEGIN x = 1; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

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
    #  - myrow tablename%ROWTYPE;
    #  - myfield tablename.columnname%TYPE;
    #  - cursors

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

    def test_get_diagnostics_basic(self) -> None:
        cases = [
            "GET DIAGNOSTICS integer_var = ROW_COUNT;",
            "GET DIAGNOSTICS text_var = PG_CONTEXT;",
            "GET DIAGNOSTICS oid_var = PG_ROUTINE_OID;",
            "GET CURRENT DIAGNOSTICS integer_var = ROW_COUNT;",
            "GET STACKED DIAGNOSTICS integer_var = ROW_COUNT;",
            "GET DIAGNOSTICS v := ROW_COUNT;",
            "GET DIAGNOSTICS a = ROW_COUNT, b := PG_CONTEXT;",
        ]
        for sql in cases:
            with self.subTest(sql=sql):
                expr = sqlglot.parse_one(sql, dialect=plpgsql)
                self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_get_diagnostics_nested(self) -> None:
        sqls = [
            "BEGIN GET DIAGNOSTICS a = ROW_COUNT, b := PG_CONTEXT; END;",
            "BEGIN GET STACKED DIAGNOSTICS a = ROW_COUNT; END;",
        ]
        for sql in sqls:
            with self.subTest(sql=sql):
                expr = sqlglot.parse_one(sql, dialect=plpgsql)
                self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_get_diagnostics_negative(self) -> None:
        bad_cases = [
            "GET DIAGNOSTICS;",
            "GET CURRENT integer_var = ROW_COUNT;",
            "GET STACKED integer_var = ROW_COUNT;",
            "GET DIAGNOSTICS integer_var ROW_COUNT;",
            "GET DIAGNOSTICS = ROW_COUNT;",
            "GET DIAGNOSTICS integer_var = ;",
            "GET DIAGNOSTICS integer_var = ROW_COUNT,;",
        ]
        for sql in bad_cases:
            with self.subTest(sql=sql):
                with self.assertRaises(sqlglot.errors.ParseError):
                    sqlglot.parse_one(sql, dialect=plpgsql)

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

    # Cursor declaration tests
    def test_plpgsql_declare_cursor_simple(self) -> None:
        sql = """
        DECLARE
            curs2 CURSOR FOR SELECT * FROM tenk1;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(
            out,
            "DECLARE curs2 CURSOR FOR SELECT * FROM tenk1; BEGIN SELECT 1; END",
        )

    def test_plpgsql_declare_cursor_with_args(self) -> None:
        sql = """
        DECLARE
            curs3 CURSOR (key integer) FOR SELECT * FROM tenk1 WHERE unique1 = key;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(
            out,
            "DECLARE curs3 CURSOR(key INTEGER) FOR SELECT * FROM tenk1 WHERE unique1 = key; BEGIN SELECT 1; END",
        )

    def test_plpgsql_declare_scroll_cursor(self) -> None:
        sql = "DECLARE c SCROLL CURSOR FOR SELECT 1; BEGIN SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_declare_no_scroll_cursor(self) -> None:
        sql = "DECLARE c NO SCROLL CURSOR FOR SELECT 1; BEGIN SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_declare_cursor_multi_args(self) -> None:
        sql = (
            "DECLARE c CURSOR(a integer, b text) FOR SELECT 1; BEGIN SELECT 1; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(
            expr.sql(dialect=plpgsql),
            "DECLARE c CURSOR(a INTEGER, b TEXT) FOR SELECT 1; BEGIN SELECT 1; END",
        )

    def test_plpgsql_declare_cursor_issue_example(self) -> None:
        sql = """
        DECLARE
            curs1 refcursor;
            curs2 CURSOR FOR SELECT * FROM tenk1;
            curs3 CURSOR (key integer) FOR SELECT * FROM tenk1 WHERE unique1 = key;
        BEGIN
            SELECT 1;
        END;
        """
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        out = expr.sql(dialect=plpgsql)
        self.assertEqual(
            out,
            "DECLARE curs1 REFCURSOR; curs2 CURSOR FOR SELECT * FROM tenk1; "
            "curs3 CURSOR(key INTEGER) FOR SELECT * FROM tenk1 WHERE unique1 = key; BEGIN SELECT 1; END",
        )

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

    def test_exception_when_sqlstate_non_string_fails(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN SQLSTATE hello THEN RAISE; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"SQLSTATE must be followed by a quoted literal"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_exception_when_sqlstate_nothing_fails(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN SQLSTATE THEN RAISE; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"SQLSTATE must be followed by a quoted literal"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_exception_when_others(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN OTHERS THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_declare_body_and_exception(self) -> None:
        sql = "DECLARE a INTEGER; BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exception_requires_when_fails(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION END;", dialect=plpgsql)

    def test_when_requires_condition_fails(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION WHEN THEN RAISE; END;", dialect=plpgsql)

    def test_when_requires_statement_fails(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION WHEN division_by_zero THEN END;", dialect=plpgsql)

    def test_return_bare(self) -> None:
        sql = "BEGIN RETURN; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_expression(self) -> None:
        sql = "BEGIN RETURN 1 + 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_level_message_with_arg_variable(self) -> None:
        sql = "BEGIN RAISE NOTICE 'Calling cs_create_job(%)', v_job_id; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_condition_bare(self) -> None:
        sql = "BEGIN RAISE division_by_zero; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_level_sqlstate(self) -> None:
        sql = "BEGIN RAISE WARNING SQLSTATE '22012'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_condition_using_message_concat(self) -> None:
        sql = "BEGIN RAISE unique_violation USING MESSAGE = 'Duplicate user ID: ' || user_id; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_bare(self) -> None:
        sql = "BEGIN RAISE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_level_using_only(self) -> None:
        sql = "BEGIN RAISE INFO USING MESSAGE := 'hello', DETAIL := 'world'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_message_with_args(self) -> None:
        sql = "BEGIN RAISE EXCEPTION 'oops: % %', 1, 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # TODO: don't rewrite := to =
    def test_raise_using_equals_normalized(self) -> None:
        sql = "BEGIN RAISE USING MESSAGE = 'x', HINT = 'y'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_condition_using(self) -> None:
        sql = "BEGIN RAISE unique_violation USING CONSTRAINT := 'users_pkey'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_raise_sqlstate_non_string_fails(self) -> None:
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"SQLSTATE must be followed by a quoted literal"
        ):
            sqlglot.parse_one("BEGIN RAISE SQLSTATE 22012; END;", dialect=plpgsql)

    def test_return_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RETURN; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_query_simple(self) -> None:
        sql = "BEGIN RETURN QUERY SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # RETURN QUERY EXECUTE command-string [ USING expression [, ... ] ];
    def test_return_query_execute_basic(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT 1'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_query_execute_using(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT $1, $2' USING a, UPPER(b); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_query_execute_inside_exception(self) -> None:
        sql = (
            "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RETURN QUERY EXECUTE 'SELECT 2'; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_query_execute_format_command(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE FORMAT('SELECT %s', x); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_query_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RETURN QUERY SELECT 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # Negative cases for RETURN QUERY EXECUTE
    def test_return_query_execute_using_missing_list_fails(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT 1' USING; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_return_query_execute_using_trailing_comma_fails(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT 1' USING a,; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_return_query_execute_into_fails(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT 1' INTO v; END;"
        with self.assertRaisesRegex(sqlglot.errors.ParseError, r"INTO is not allowed in RETURN QUERY EXECUTE"):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_return_query_execute_into_strict_fails(self) -> None:
        sql = "BEGIN RETURN QUERY EXECUTE 'SELECT 1' INTO STRICT v; END;"
        with self.assertRaisesRegex(sqlglot.errors.ParseError, r"INTO is not allowed in RETURN QUERY EXECUTE"):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_return_next_simple(self) -> None:
        sql = "BEGIN RETURN NEXT 1 + 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_next_parameter(self) -> None:
        sql = "BEGIN RETURN NEXT $1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_return_next_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RETURN NEXT 3; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_loop_empty_fails(self) -> None:
        sql = "BEGIN LOOP END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_loop_with_return(self) -> None:
        sql = "BEGIN LOOP RETURN; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_loop_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN LOOP RETURN; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_bare(self) -> None:
        sql = "BEGIN EXIT; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_with_label(self) -> None:
        sql = "BEGIN EXIT myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_with_when(self) -> None:
        sql = "BEGIN EXIT WHEN x > 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_with_label_and_when(self) -> None:
        sql = "BEGIN EXIT myloop WHEN x > 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN EXIT; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_exit_inside_loop(self) -> None:
        sql = "BEGIN LOOP EXIT; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_bare(self) -> None:
        sql = "BEGIN CONTINUE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_with_label(self) -> None:
        sql = "BEGIN CONTINUE myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_with_when(self) -> None:
        sql = "BEGIN CONTINUE WHEN x > 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_with_label_and_when(self) -> None:
        sql = "BEGIN CONTINUE myloop WHEN x > 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN CONTINUE; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_continue_inside_loop(self) -> None:
        sql = "BEGIN LOOP CONTINUE; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_simple(self) -> None:
        sql = "BEGIN OPEN c FOR SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_with_scroll(self) -> None:
        sql = "BEGIN OPEN c SCROLL FOR SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_with_no_scroll(self) -> None:
        sql = "BEGIN OPEN c NO SCROLL FOR SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_inside_loop(self) -> None:
        sql = "BEGIN LOOP OPEN c FOR SELECT 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_no_args(self) -> None:
        sql = "BEGIN OPEN curs2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_positional_arg(self) -> None:
        sql = "BEGIN OPEN curs3(42); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_named_colon_arg(self) -> None:
        sql = "BEGIN OPEN curs3(key := 42); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_named_arrow_arg(self) -> None:
        sql = "BEGIN OPEN curs3(key => 42); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_mixed_arg(self) -> None:
        sql = "BEGIN OPEN curs3(a => b, c := 10); END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_bound_cursor_variable_select(self) -> None:
        sql = "BEGIN OPEN $1 FOR SELECT 1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_for_execute_simple(self) -> None:
        sql = "BEGIN OPEN c FOR EXECUTE q; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_for_execute_using(self) -> None:
        sql = "BEGIN OPEN curs1 FOR EXECUTE FORMAT('SELECT 1 WHERE x = $1') USING keyvalue; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_for_execute_with_scroll(self) -> None:
        sql = "BEGIN OPEN c SCROLL FOR EXECUTE q USING x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_for_execute_with_no_scroll(self) -> None:
        sql = "BEGIN OPEN c NO SCROLL FOR EXECUTE q USING x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_open_cursor_for_execute_ast_shape(self) -> None:
        sql = "BEGIN OPEN c FOR EXECUTE 'SELECT 1' USING x; END;"
        block = sqlglot.parse_one(sql, dialect=plpgsql)
        open_node = block.find(PGOpenCursor)
        self.assertIsNotNone(open_node)
        assert open_node is not None  # for type checkers
        self.assertIsInstance(open_node.args["expression"], PGExecute)
        self.assertEqual(len(open_node.args["expression"].args["using"]), 1)
        self.assertEqual(open_node.args["expression"].args["using"][0].name, "x")

    def test_open_cursor_for_execute_into_fails(self) -> None:
        sql = "BEGIN OPEN c FOR EXECUTE 'SELECT 1' INTO v; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"INTO is not allowed in OPEN FOR EXECUTE"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_open_cursor_for_execute_into_strict_fails(self) -> None:
        sql = "BEGIN OPEN c FOR EXECUTE 'SELECT 1' INTO STRICT v; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"INTO is not allowed in OPEN FOR EXECUTE"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_fetch_cursor_into_single(self) -> None:
        sql = "BEGIN FETCH curs1 INTO rowvar; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_cursor_into_multiple(self) -> None:
        sql = "BEGIN FETCH curs2 INTO foo, bar, baz; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_with_direction_from(self) -> None:
        sql = "BEGIN FETCH LAST FROM curs3 INTO x, y; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_relative_with_count(self) -> None:
        sql = "BEGIN FETCH RELATIVE -2 FROM curs4 INTO x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_absolute_with_count_in(self) -> None:
        sql = "BEGIN FETCH ABSOLUTE 5 IN curs4 INTO x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # MOVE tests
    def test_move_simple_cursor(self) -> None:
        sql = "BEGIN MOVE curs1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_last_from_cursor(self) -> None:
        sql = "BEGIN MOVE LAST FROM curs3; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_relative_negative_from_cursor(self) -> None:
        sql = "BEGIN MOVE RELATIVE -2 FROM curs4; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_forward_count_from_cursor(self) -> None:
        sql = "BEGIN MOVE FORWARD FROM curs4; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # New FETCH direction forms
    def test_fetch_count_from_cursor(self) -> None:
        sql = "BEGIN FETCH 5 FROM curs5 INTO x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_all_from_cursor(self) -> None:
        sql = "BEGIN FETCH ALL FROM curs5 INTO x; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_forward_count_from_cursor(self) -> None:
        sql = "BEGIN FETCH FORWARD 3 FROM curs6 INTO a, b; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_forward_all_from_cursor(self) -> None:
        sql = "BEGIN FETCH FORWARD ALL FROM curs6 INTO a; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_backward_count_from_cursor(self) -> None:
        sql = "BEGIN FETCH BACKWARD 2 FROM curs7 INTO col; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_fetch_backward_all_from_cursor(self) -> None:
        sql = "BEGIN FETCH BACKWARD ALL FROM curs7 INTO col; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # New MOVE direction forms
    def test_move_forward_count(self) -> None:
        sql = "BEGIN MOVE FORWARD 4 FROM curs8; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_forward_all(self) -> None:
        sql = "BEGIN MOVE FORWARD ALL FROM curs8; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_backward_count(self) -> None:
        sql = "BEGIN MOVE BACKWARD 2 FROM curs9; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_move_backward_all(self) -> None:
        sql = "BEGIN MOVE BACKWARD ALL FROM curs9; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_close_cursor_in_block(self) -> None:
        sql = "BEGIN CLOSE curs1; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # ASSERT tests
    def test_assert_simple(self) -> None:
        sql = "BEGIN ASSERT x > 0; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_assert_with_message(self) -> None:
        sql = "BEGIN ASSERT x > 0, 'bad'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_assert_inside_loop(self) -> None:
        sql = "BEGIN LOOP ASSERT TRUE; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_assert_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN ASSERT x > 0; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # WHILE tests
    def test_plpgsql_while_simple(self) -> None:
        sql = "BEGIN WHILE x < 10 LOOP x := x + 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_while_cond_or(self) -> None:
        sql = "BEGIN WHILE x < 10 OR x < 5 LOOP x := x + 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_while_cond_and(self) -> None:
        sql = "BEGIN WHILE x < 10 AND x < 5 LOOP x := x + 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_while_with_label(self) -> None:
        sql = "BEGIN WHILE TRUE LOOP EXIT; END LOOP mylabel; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_nested_while_and_loop(self) -> None:
        sql = "BEGIN WHILE x < 5 LOOP LOOP CONTINUE; END LOOP; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_plpgsql_while_requires_loop_keyword_fails(self) -> None:
        sql = "BEGIN WHILE x < 10 SELECT 1; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_plpgsql_while_requires_end_loop_fails(self) -> None:
        sql = "BEGIN WHILE TRUE LOOP SELECT 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_if_found(self) -> None:
        sql = "BEGIN IF FOUND THEN RETURN 1; END IF; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_simple_update(self) -> None:
        sql = (
            "BEGIN IF v_user_id <> 0 THEN "
            "UPDATE users SET email = v_email WHERE user_id = v_user_id; "
            "END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_elsif_else_full(self) -> None:
        sql = (
            "BEGIN IF number = 0 THEN result := 'zero'; "
            "ELSIF number > 0 THEN result := 'positive'; "
            "ELSIF number < 0 THEN result := 'negative'; "
            "ELSE result := 'NULL'; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_with_else_only(self) -> None:
        sql = (
            "BEGIN IF flag THEN a := 1; ELSE a := 2; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_single_elsif_no_else(self) -> None:
        sql = (
            "BEGIN IF x = 1 THEN a := 1; ELSIF x = 2 THEN a := 2; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_multiple_statements_in_branch(self) -> None:
        sql = (
            "BEGIN IF x > 0 THEN a := 1; b := 2; ELSE a := 3; b := 4; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_inside_loop(self) -> None:
        sql = (
            "BEGIN LOOP IF x > 0 THEN a := 1; ELSE a := 2; END IF; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_inside_while(self) -> None:
        sql = (
            "BEGIN WHILE x < 3 LOOP IF x = 1 THEN a := 1; ELSE a := 0; END IF; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_if_inside_exception_when(self) -> None:
        sql = (
            "BEGIN EXCEPTION WHEN division_by_zero THEN IF x = 0 THEN a := 0; ELSE a := 1; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_nested_if_inside_if(self) -> None:
        sql = (
            "BEGIN IF a THEN IF b THEN x := 1; ELSE x := 2; END IF; ELSE x := 3; END IF; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_elseif_spelling_accepted_and_normalized(self) -> None:
        sql = (
            "BEGIN IF x = 0 THEN a := 0; ELSEIF x = 1 THEN a := 1; ELSE a := 2; END IF; END;"
        )
        # Parser should accept ELSEIF and generator should normalize to ELSIF
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        normalized = (
            "BEGIN IF x = 0 THEN a := 0; ELSIF x = 1 THEN a := 1; ELSE a := 2; END IF; END"
        )
        self.assertEqual(expr.sql(dialect=plpgsql), normalized)

    def test_if_missing_then_raises(self) -> None:
        sql = "BEGIN IF x > 0 SELECT 1; END IF; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_if_missing_end_if_raises(self) -> None:
        sql = "BEGIN IF x > 0 THEN a := 1; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_if_empty_branch_raises(self) -> None:
        sql = "BEGIN IF x > 0 THEN END IF; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    # FOR ... IN <query> LOOP tests
    def test_for_in_query_simple(self) -> None:
        sql = (
            "BEGIN FOR r_user IN SELECT username FROM users LOOP "
            "RAISE NOTICE 'Username: %', r_user.username; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_query_empty_body_fails(self) -> None:
        sql = "BEGIN FOR r IN SELECT 1 LOOP END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_query_multiple_statements(self) -> None:
        sql = "BEGIN FOR r IN SELECT id FROM t LOOP a := 1; b := 2; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_query_with_label(self) -> None:
        sql = "BEGIN FOR r IN SELECT 1 LOOP EXIT; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_query_with_where(self) -> None:
        sql = "BEGIN FOR r IN SELECT a FROM t WHERE a > 0 LOOP a := a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_query_nested_loop(self) -> None:
        sql = "BEGIN FOR r IN SELECT 1 LOOP LOOP CONTINUE; END LOOP; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_query_missing_loop_fails(self) -> None:
        sql = "BEGIN FOR r IN SELECT 1 SELECT 2; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_query_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOR r IN SELECT 1 LOOP a := 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_cursor_simple(self) -> None:
        sql = "BEGIN FOR rec IN cur LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_positional_arg(self) -> None:
        sql = "BEGIN FOR rec IN cur(42) LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_positional_args(self) -> None:
        sql = "BEGIN FOR rec IN cur('IT', 75000) LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_named_colon_args(self) -> None:
        sql = "BEGIN FOR rec IN cur(dept_param := 'IT', min_sal := 75000) LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_named_arrow_args(self) -> None:
        sql = "BEGIN FOR rec IN cur(dept_param => 'IT', min_sal => 75000) LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_mixed_named_args(self) -> None:
        sql = "BEGIN FOR rec IN cur(dept_param := 'IT', min_sal => 75000) LOOP a := rec.a; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_with_label(self) -> None:
        sql = "BEGIN FOR rec IN cur LOOP EXIT; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_cursor_ast_shape(self) -> None:
        sql = "BEGIN FOR rec IN cur(dept_param := 'IT', min_sal => 75000) LOOP NULL; END LOOP; END;"
        block = sqlglot.parse_one(sql, dialect=plpgsql)
        for_in = block.find(PGForIn)
        self.assertIsNotNone(for_in)
        assert for_in is not None
        self.assertIsInstance(for_in.args["query"], PGCursorCall)
        self.assertEqual(for_in.args["query"].args["this"].name, "cur")
        args = for_in.args["query"].args["expressions"]
        self.assertEqual(len(args), 2)
        self.assertIsInstance(args[0], sqlglot.exp.PropertyEQ)
        self.assertIsInstance(args[1], sqlglot.exp.Kwarg)

    def test_for_in_cursor_missing_close_paren_fails(self) -> None:
        sql = "BEGIN FOR rec IN cur(1 LOOP a := rec.a; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_cursor_trailing_comma_fails(self) -> None:
        sql = "BEGIN FOR rec IN cur(1,) LOOP a := rec.a; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_cursor_missing_loop_fails(self) -> None:
        sql = "BEGIN FOR rec IN cur(1) a := rec.a; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_cursor_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOR rec IN cur(1) LOOP a := rec.a; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_cursor_invalid_named_arg_fails(self) -> None:
        sql = "BEGIN FOR rec IN cur(name :=) LOOP a := rec.a; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    # FOR ... IN <range> LOOP tests
    def test_for_range_simple(self) -> None:
        sql = "BEGIN FOR i IN 1..10 LOOP a := i; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_reverse(self) -> None:
        sql = "BEGIN FOR i IN REVERSE 10..1 LOOP a := i; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_reverse_by(self) -> None:
        sql = "BEGIN FOR i IN REVERSE 10..1 BY 2 LOOP a := i; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_by_no_reverse(self) -> None:
        sql = "BEGIN FOR i IN 1..10 BY 2 LOOP a := i; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_with_label(self) -> None:
        sql = "BEGIN FOR i IN 1..3 LOOP EXIT; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_multiple_statements(self) -> None:
        sql = "BEGIN FOR i IN 1..3 LOOP a := 1; b := 2; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_expression_bounds(self) -> None:
        sql = "BEGIN FOR i IN (a + 1)..(b * 2) LOOP a := i; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_nested_loop(self) -> None:
        sql = "BEGIN FOR i IN 1..3 LOOP LOOP CONTINUE; END LOOP; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_range_missing_loop_fails(self) -> None:
        sql = "BEGIN FOR i IN 1..10 a := 1; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    # FOR ... IN EXECUTE ... LOOP tests
    def test_for_in_execute_simple(self) -> None:
        sql = (
            "BEGIN FOR user_row IN EXECUTE query_str LOOP "
            "RAISE NOTICE 'User ID: %, Username: %', user_row.id, user_row.username; "
            "END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_literal_command(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE 'SELECT 1' LOOP RETURN; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_using_single(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE 'SELECT $1' USING a LOOP a := 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_using_multiple(self) -> None:
        sql = (
            "BEGIN FOR r IN EXECUTE 'SELECT $1, $2' USING a, UPPER(b) LOOP "
            "RETURN; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_concat_command(self) -> None:
        sql = (
            "BEGIN FOR r IN EXECUTE 'SELECT * FROM ' || QUOTE_IDENT(tabname) LOOP "
            "RETURN; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_format_command(self) -> None:
        sql = (
            "BEGIN FOR r IN EXECUTE FORMAT('SELECT %s', x) USING y LOOP "
            "RETURN; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_with_label(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q LOOP EXIT; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_multiple_statements(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q LOOP a := 1; b := 2; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_nested_loop(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q LOOP LOOP CONTINUE; END LOOP; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_inside_exception_when(self) -> None:
        sql = (
            "BEGIN SELECT 1; EXCEPTION WHEN OTHERS THEN "
            "FOR r IN EXECUTE q LOOP a := 1; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_for_in_execute_ast_shape(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q USING a LOOP RETURN; END LOOP; END;"
        block = sqlglot.parse_one(sql, dialect=plpgsql)
        forin = block.find(PGForIn)
        self.assertIsNotNone(forin)
        assert forin is not None  # for type checkers
        self.assertEqual(forin.this.name, "r")
        self.assertIsInstance(forin.args["query"], PGExecute)
        self.assertEqual(len(forin.args["query"].args["using"]), 1)

    # Negative cases
    def test_for_in_execute_into_fails(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE 'SELECT 1' INTO v LOOP RETURN; END LOOP; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"INTO is not allowed in FOR IN EXECUTE"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_execute_into_strict_fails(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE 'SELECT 1' INTO STRICT v LOOP RETURN; END LOOP; END;"
        with self.assertRaisesRegex(
            sqlglot.errors.ParseError, r"INTO is not allowed in FOR IN EXECUTE"
        ):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_execute_using_trailing_comma_fails(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q USING a, LOOP RETURN; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_in_execute_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOR r IN EXECUTE q LOOP a := 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_for_range_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOR i IN 1..10 LOOP a := 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    # FOREACH ... IN ARRAY LOOP tests
    def test_foreach_simple(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP s := s + x; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_issue_example(self) -> None:
        # The exact example from the feature request (RETURN follows the loop).
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP s := s + x; END LOOP; RETURN s; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_with_slice(self) -> None:
        sql = "BEGIN FOREACH x SLICE 1 IN ARRAY $1 LOOP a := 1; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_array_literal(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY ARRAY[1, 2, 3] LOOP a := x; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_multiple_statements(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP a := 1; b := 2; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_with_label(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP EXIT; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_slice_with_label(self) -> None:
        sql = "BEGIN FOREACH x SLICE 2 IN ARRAY $1 LOOP a := 1; END LOOP myloop; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_nested_loop(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP LOOP CONTINUE; END LOOP; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_inside_exception_when(self) -> None:
        sql = (
            "BEGIN SELECT 1; EXCEPTION WHEN OTHERS THEN "
            "FOREACH x IN ARRAY $1 LOOP a := x; END LOOP; END;"
        )
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_foreach_ast_shape(self) -> None:
        sql = "BEGIN FOREACH x SLICE 1 IN ARRAY $1 LOOP a := 1; END LOOP; END;"
        block = sqlglot.parse_one(sql, dialect=plpgsql)
        foreach = block.find(PGForEach)
        self.assertIsNotNone(foreach)
        assert foreach is not None  # for type checkers
        self.assertEqual(foreach.this.name, "x")
        self.assertEqual(foreach.args["slice"].name, "1")
        self.assertEqual(len(foreach.args["expressions"]), 1)

    def test_foreach_missing_loop_fails(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 a := 1; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_foreach_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOREACH x IN ARRAY $1 LOOP a := 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_foreach_missing_array_fails(self) -> None:
        sql = "BEGIN FOREACH x IN $1 LOOP a := 1; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_foreach_missing_in_fails(self) -> None:
        sql = "BEGIN FOREACH x ARRAY $1 LOOP a := 1; END LOOP; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_execute_inside_block(self) -> None:
        sql = "BEGIN EXECUTE 'SELECT 1'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_concat_command(self) -> None:
        sql = "EXECUTE 'SELECT count(*) FROM ' || QUOTE_IDENT(tabname);"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_format_command(self) -> None:
        sql = "EXECUTE FORMAT('SELECT count(*)');"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_format_command_with_args(self) -> None:
        sql = "EXECUTE FORMAT('UPDATE tbl SET %I = $1 WHERE key = $2', colname) USING newvalue, keyvalue;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_into_single(self) -> None:
        sql = "EXECUTE 'SELECT a' INTO var1;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_into_multiple(self) -> None:
        sql = "EXECUTE 'SELECT a, b, c' INTO var1, var2, var3;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_into_strict_single(self) -> None:
        sql = "EXECUTE 'SELECT a' INTO STRICT var1;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    # EXECUTE ... USING tests
    def test_execute_using_single(self) -> None:
        sql = "EXECUTE 'SELECT $1' USING a;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_using_multiple_with_function(self) -> None:
        sql = "EXECUTE 'SELECT $1, $2' USING a, UPPER(b);"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_into_using(self) -> None:
        sql = "EXECUTE 'SELECT a' INTO var1 USING x;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_into_strict_using(self) -> None:
        sql = "EXECUTE 'SELECT a, b' INTO STRICT var1, var2 USING x, y;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_using_inside_block(self) -> None:
        sql = "BEGIN EXECUTE 'SELECT $1' USING a; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_execute_using_missing_list_fails(self) -> None:
        sql = "EXECUTE 'SELECT 1' USING;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_execute_using_trailing_comma_fails(self) -> None:
        sql = "EXECUTE 'SELECT 1' USING a,;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    def test_execute_invalid_order_using_before_into_fails(self) -> None:
        sql = "EXECUTE 'SELECT 1' USING a INTO v;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)

    # FOUND testsdd
    def test_found_in_case_when(self) -> None:
        sql = "BEGIN a := CASE WHEN FOUND THEN 'Success' ELSE 'Failed' END; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_found_assert(self) -> None:
        sql = "BEGIN ASSERT FOUND, 'Inventory item 500 does not exist!'; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_found_exit_when_not(self) -> None:
        sql = "BEGIN LOOP EXIT WHEN NOT FOUND; END LOOP; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_found_assignment(self) -> None:
        sql = "BEGIN a := FOUND; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_found_raise_notice(self) -> None:
        sql = "BEGIN RAISE NOTICE 'User lookup completed. Record located? %', FOUND; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

    def test_found_ast_is_pgfound(self) -> None:
        expr = sqlglot.parse_one("BEGIN a := FOUND; END;", dialect=plpgsql)
        # Ensure it's a PGFound instead of a Column
        self.assertTrue(any(isinstance(n, PGFound) for n in expr.walk()))
        self.assertFalse(any(
            isinstance(n, exp.Column) and n.name.upper() == "FOUND"
            for n in expr.walk()
        ))

    def test_found_not_ast_shape(self) -> None:
        expr = sqlglot.parse_one(
            "BEGIN IF NOT FOUND THEN RETURN 1; END IF; END;", dialect=plpgsql
        )
        not_nodes = [n for n in expr.walk() if isinstance(n, exp.Not)]
        self.assertTrue(not_nodes)
        self.assertIsInstance(not_nodes[0].this, PGFound)
