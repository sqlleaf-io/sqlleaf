from __future__ import annotations

from sqlglot.dialects.postgres import Postgres

from plpgsql.p_generator import Generator
from plpgsql.p_parser import Parser, TokenType


class PlPgSQL(Postgres):
    """
    A custom dialect that extends Postgres to parse PL/pgSQL.
    """
    class Tokenizer(Postgres.Tokenizer):
        KEYWORDS = {
            **Postgres.Tokenizer.KEYWORDS,
            "ASSERT": TokenType.ASSERT,
            "CLOSE": TokenType.CLOSE,
            "CONTINUE": TokenType.CONTINUE,
            "DECLARE": TokenType.DECLARE,
            "EXIT": TokenType.EXIT,
            "FOREACH": TokenType.FOREACH,
            "GET": TokenType.GET,
            "IF": TokenType.IF,
            "LOOP": TokenType.LOOP,
            "MOVE": TokenType.MOVE,
            "OPEN": TokenType.OPEN,
            "RAISE": TokenType.RAISE,
            "RETURN": TokenType.RETURN,
            "WHILE": TokenType.WHILE,
        }

        # In base sqlglot, FETCH and EXECUTE are treated as COMMANDs, which swallow the rest
        # of the statement as a single STRING token, so we exclude them.
        COMMANDS = Postgres.Tokenizer.COMMANDS - {TokenType.FETCH, TokenType.EXECUTE}

    Generator = Generator
    Parser = Parser

plpgsql = PlPgSQL
