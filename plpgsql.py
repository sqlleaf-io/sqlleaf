from __future__ import annotations

"""
Example custom dialect that extends Postgres to parse simple PL/pgSQL-style blocks.

This dialect recognizes the statement form:

    BEGIN
    END;

This change extends support to accept any SQL statements between BEGIN and
END and stores them in the PGBlock.expressions list.

Usage:
    >>> import sqlglot
    >>> from plpgsql import plpgsql
    >>> tree = sqlglot.parse_one("BEGIN END;", dialect=plpgsql)
    >>> type(tree).__name__
    'PGBlock'
    >>> tree.sql(dialect=plpgsql)
    'BEGIN END'
"""

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.generators.postgres import PostgresGenerator
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import TokenType


class PGBlock(exp.Expression):
    """A Postgres-specific BEGIN ... END block.

    Stores inner statements in ``expressions``.
    """
    # Allow empty blocks: 'expressions' is optional
    arg_types = {"expressions": False, "begin": False}


class PlPgSQL(Postgres):
    """A minimal PL/pgSQL-like dialect extending Postgres.

    - Tokenizer: inherit from Postgres (BEGIN/END already mapped)
    - Parser: treat BEGIN ... END as a top-level statement and parse it into exp.Block
    - Generator: reuse Postgres generator (already knows how to render Block)
    """

    class Parser(PostgresParser):
        STATEMENT_PARSERS = {
            **PostgresParser.STATEMENT_PARSERS,
            TokenType.BEGIN: lambda self: self._parse_plpgsql_block(),
        }

        def _parse_plpgsql_block(self) -> PGBlock:
            # BEGIN
            self._match(TokenType.BEGIN)

            expressions: list[exp.Expression] = []

            while True:
                # If we've consumed the current chunk, move to the next one
                if self._index >= self._tokens_size:
                    self._advance_chunk()

                # Stop if we reached END (block terminator)
                if not self._curr:
                    break

                if self._match(TokenType.END, advance=False):
                    self._advance()  # consume END
                    break

                stmt = self._parse_statement()
                if stmt is not None:
                    expressions.append(stmt)

                # After parsing a statement, if we haven't consumed the chunk, it's an error
                if self._index < self._tokens_size:
                    self.raise_error("Invalid expression / Unexpected token")

                # Proceed to next chunk for the following statement or END
                self.check_errors()
                self._advance_chunk()

            return self.expression(PGBlock(expressions=expressions, begin=True))

    class Generator(PostgresGenerator):
        # Provide explicit transform to ensure support for PGBlock
        TRANSFORMS = {
            **getattr(PostgresGenerator, "TRANSFORMS", {}),
            PGBlock: lambda self, e: self.pgblock_sql(e),
        }

        # Also expose the auto-discovered method
        def pgblock_sql(self, expression: PGBlock) -> str:
            parts = ["BEGIN"]
            for expr in expression.expressions:
                parts.append(f"{self.sql(expr)};")
            parts.append("END")
            return " ".join(parts)


plpgsql = PlPgSQL
