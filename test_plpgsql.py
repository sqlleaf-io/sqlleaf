import unittest

import sqlglot
from plpgsql import plpgsql


class TestPlPgSQL(unittest.TestCase):
    def test_begin_end_roundtrip(self) -> None:
        sql = "BEGIN END;"
        expr = sqlglot.parse_one(sql, dialect=plpgsql)
        self.assertEqual(expr.sql(dialect=plpgsql), sql[:-1])
