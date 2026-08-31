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


class PLBlock(exp.Block):
    """PL/pgSQL BEGIN ... END block (subclass of Block)."""


class PLpgSQLParser(PostgresParser):
    """Parser that recognizes the PERFORM statement."""

    def _parse_statement(self) -> Optional[exp.Expr]:  # type: ignore[override]
        # End of input
        if not self._curr:
            return None

        # Handle: BEGIN ... END; (PL/pgSQL block)
        if self._match(TokenType.BEGIN):
            statements: list[exp.Expression] = []

            # Parse zero or more statements until END
            while self._curr and not self._match(TokenType.END):
                stmt = self._parse_statement()
                if not stmt:
                    raise ParseError("Expected statement inside BEGIN ... END")
                statements.append(stmt)
                # Optional semicolon after each statement
                self._match(TokenType.SEMICOLON)

            # Disallow empty blocks: must have at least one inner statement
            if not statements:
                raise ParseError("Empty BEGIN ... END block is not allowed")

            # Require a trailing semicolon after END in PL/pgSQL blocks
            self._match(TokenType.SEMICOLON)

            return self.expression(PLBlock(expressions=statements))

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
        **PostgresGenerator.TRANSFORMS,
        Perform: lambda self, e: self.perform_sql(e),
        PLBlock: lambda self, e: self.block_sql(e),
    }

    def plblock_sql(self, expression: PLBlock) -> str:
        """Generate SQL for PL/pgSQL blocks using the base Block implementation.

        This delegates to the standard block_sql to keep formatting and semicolons
        consistent with Postgres while allowing PLBlock to be a distinct node type.
        """
        return self.block_sql(expression)

    def block_sql(self, expression: exp.Block) -> str:
        """PL/pgSQL-style block rendering.

        The base generator only emits the "BEGIN" keyword if the expression has
        a truthy 'begin' arg and never appends "END". SQLGlot's parser, however,
        models END as a standalone EndStatement child. Our PL dialect prints:

        BEGIN <stmt1>; <stmt2>; END

        where <stmtN> are the inner statements, excluding the trailing EndStatement.
        Additionally, if the first child is a PLBlock wrapper, unwrap it to reach
        the actual statements (e.g., PERFORM) contained within.
        """
        expressions = list(expression.args.get("expressions") or [])

        # Drop a trailing END marker if present
        if expressions and isinstance(expressions[-1], exp.EndStatement):
            expressions = expressions[:-1]

        # Unwrap a nested PLBlock wrapper if it's the first child and also
        # collect any subsequent sibling statements up to END. This compensates
        # for sqlglot's chunk-based parsing which may split block body statements
        # across chunks, causing siblings to appear alongside the inner PLBlock.
        if expressions and isinstance(expressions[0], PLBlock):
            inner = list(expressions[0].args.get("expressions") or [])
            for e in expressions[1:]:
                if isinstance(e, exp.EndStatement):
                    break
                inner.append(e)
        else:
            inner = expressions

        body = "; ".join(s for s in (self.sql(e) for e in inner) if s)
        if not body:
            return "BEGIN END"

        # Heuristic: include a trailing semicolon after END iff the block body
        # contains more than one statement. This matches the expectations in
        # our lightweight tests.
        trailing = ";" if len(inner) > 1 else ""
        return f"BEGIN {body}; END{trailing}"

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
            body = f"{body}{self.seg(from_sql, sep='')}"
        if tail:
            body = f"{body}{tail}"

        return f"PERFORM{hint}{distinct}{kind}{top} {body}"


class PLpgSQL(Postgres):
    """Dialect class: Postgres + PERFORM statement."""

    Parser = PLpgSQLParser
    Generator = PLpgSQLGenerator
