from __future__ import annotations

"""
Example custom dialect that extends Postgres to parse simple PL/pgSQL-style blocks.

This dialect recognizes the statement form:

    BEGIN
    END;

There is no support for statements inside the block yet — we only parse the
BEGIN/END pair and produce an exp.PGBlock node.

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
    """A Postgres-specific empty BEGIN ... END block.

    For now, this is a thin subclass of exp.Block to allow the parser to
    construct a distinct node type (PGBlock) for PL/pgSQL BEGIN blocks.
    """
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
            # Consume BEGIN and the matching END to form an empty PG block
            self._match(TokenType.BEGIN)
            # No inner statements are supported yet; just require END
            self._match(TokenType.END)
            # Create an empty PGBlock (no EndStatement inside)
            return self.expression(PGBlock(expressions=[], begin=True))

    class Generator(PostgresGenerator):
        TRANSFORMS = {
            PGBlock: lambda self, e: "BEGIN END",
        }

        # Also keep the auto-discovered method (harmless redundancy)
        def pgblock_sql(self, expression: PGBlock) -> str:
            return "BEGIN END"


plpgsql = PlPgSQL
