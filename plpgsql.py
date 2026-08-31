from __future__ import annotations

"""
Custom PL/pgSQL-like dialect that extends Postgres and supports the PERFORM statement.

Usage:
    from sqlglot import parse_one
    from plpgsql import PLpgSQL

    tree = parse_one("PERFORM my_function()", dialect=PLpgSQL)
    assert tree.__class__.__name__ == "Perform"
    assert tree.args["expression"] is not None

    # Generate SQL back
    sql = tree.sql(dialect=PLpgSQL)
    assert sql == "PERFORM my_function()"
"""

from typing import Optional

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.generators.postgres import PostgresGenerator
from sqlglot.tokens import TokenType
from sqlglot.errors import ParseError


class Perform(exp.Select):
    """PL/pgSQL PERFORM statement implemented as a Select subclass.

    This makes PERFORM behave identically to SELECT (FROM, WHERE, GROUP BY, ORDER BY, LIMIT, ...),
    except that the head keyword is PERFORM and the result is discarded at runtime.
    """


class PLpgSQLParser(PostgresParser):
    """Parser that recognizes the PERFORM statement."""

    def _parse_statement(self) -> Optional[exp.Expr]:  # type: ignore[override]
        # End of input
        if not self._curr:
            return None

        # Handle: PERFORM <query_or_expression>
        if self._match_text_seq("PERFORM"):
            # Parse the first projection expression
            first_expr = self._parse_expression()

            # Build a PERFORM (as Select) seeded with the first projection
            perform = self.expression(Perform(expressions=[first_expr]))

            # Parse FROM (outside of _parse_query_modifiers)
            from_ = self._parse_from()
            if from_:
                perform.set("from_", from_)

            # Parse the rest of the query modifiers (WHERE, GROUP BY, ORDER BY, LIMIT, ...)
            perform = self._parse_query_modifiers(perform)

            # No set-ops handling for PERFORM for now; not required by tests.
            return perform

        # Fallback to standard Postgres parsing
        return super()._parse_statement()


class PLpgSQLGenerator(PostgresGenerator):
    """Generator that renders PERFORM statements."""

    # Register handler for our custom Perform node
    TRANSFORMS = {
        Perform: lambda self, e: self.perform_sql(e),
    }

    def perform_sql(self, expression: Perform) -> str:  # auto-discovered by name
        # Mirror select_sql layout with a PERFORM head
        hint = self.sql(expression, "hint")
        hint = f" {hint}" if hint else ""

        distinct = self.sql(expression, "distinct")
        distinct = f" {distinct}" if distinct else ""

        kind = self.sql(expression, "kind")
        kind = f" {kind}" if kind else ""

        # TOP ... may be stored under limit in some dialects; keep this simple for our tests
        top = ""

        projections = self.expressions(expression, key="expressions")
        from_sql = self.sql(expression, "from_")
        tail = self.query_modifiers(expression)

        body = f"{projections}"
        if from_sql:
            body = f"{body}{self.seg(from_sql, sep="")}"
        if tail:
            body = f"{body}{tail}"

        return f"PERFORM{hint}{distinct}{kind}{top} {body}"


class PLpgSQL(Postgres):
    """Dialect class: Postgres + PERFORM statement."""

    Parser = PLpgSQLParser
    Generator = PLpgSQLGenerator
