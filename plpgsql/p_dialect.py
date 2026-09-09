from __future__ import annotations

"""
Example custom dialect that extends Postgres to parse simple PL/pgSQL-style blocks.
"""

from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import TokenType
from plpgsql.p_generator import Generator
from plpgsql.p_parser import Parser


class PlPgSQL(Postgres):
    """A minimal PL/pgSQL-like dialect extending Postgres.

    - Tokenizer: inherit from Postgres (BEGIN/END already mapped)
    - Parser: treat BEGIN ... END as a top-level statement and parse it into exp.Block
    - Generator: reuse Postgres generator (already knows how to render Block)
    """

    class Tokenizer(Postgres.Tokenizer):
        # Override DECLARE to be a dedicated token in this dialect
        KEYWORDS = {
            **Postgres.Tokenizer.KEYWORDS,
            "DECLARE": TokenType.DECLARE,
        }

        # In base sqlglot, FETCH and EXECUTE are treated as COMMANDs, which swallow the rest
        # of the statement as a single STRING token, so we exclude them.
        COMMANDS = Postgres.Tokenizer.COMMANDS - {TokenType.FETCH, TokenType.EXECUTE}

    Generator = Generator
    Parser = Parser

plpgsql = PlPgSQL
