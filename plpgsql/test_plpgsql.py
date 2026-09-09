import unittest

import sqlglot
from plpgsql.p_dialect import plpgsql


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

    def test_exception_requires_when(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION END;", dialect=plpgsql)

    def test_when_requires_condition(self) -> None:
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one("BEGIN EXCEPTION WHEN THEN RAISE; END;", dialect=plpgsql)

    def test_when_requires_statement(self) -> None:
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

    # TODO: RETURN QUERY EXECUTE command-string [ USING expression [, ... ] ];

    def test_return_query_inside_exception_when(self) -> None:
        sql = "BEGIN SELECT 1; EXCEPTION WHEN division_by_zero THEN RETURN QUERY SELECT 2; END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])

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

    # TODO: OPEN unbound_cursorvar [ [ NO ] SCROLL ] FOR EXECUTE query_string [ USING expression [, ... ] ];

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

    def test_for_range_missing_end_loop_fails(self) -> None:
        sql = "BEGIN FOR i IN 1..10 LOOP a := 1; END; END;"
        with self.assertRaises(sqlglot.errors.ParseError):
            sqlglot.parse_one(sql, dialect=plpgsql)
