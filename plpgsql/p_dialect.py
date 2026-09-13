from __future__ import annotations

from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import Token

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
            "BY": TokenType.BY,
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
            "PERFORM": TokenType.PERFORM,
            "RAISE": TokenType.RAISE,
            "RETURN": TokenType.RETURN,
            "REVERSE": TokenType.REVERSE,
            "WHILE": TokenType.WHILE,
        }

        # In base sqlglot, FETCH and EXECUTE are treated as COMMANDs, which swallow the rest
        # of the statement as a single STRING token, so we exclude them.
        COMMANDS = Postgres.Tokenizer.COMMANDS - {TokenType.FETCH, TokenType.EXECUTE}

        def tokenize(self, sql: str) -> list[Token]:
            tokens = super().tokenize(sql)
            return self._merge_range_tokens(tokens)

        def _merge_range_tokens(self, tokens: list[Token]) -> list[Token]:
            def adjacent(a: Token, b: Token) -> bool:
                return a.end + 1 == b.start

            result: list[Token] = []
            i = 0
            n = len(tokens)
            while i < n:
                tok = tokens[i]
                nxt = tokens[i + 1] if i + 1 < n else None

                # Pattern 1: NUMBER('...' endswith '.') immediately followed by DOT -> DDOT
                if (
                    nxt is not None
                    and tok.token_type == TokenType.NUMBER
                    and tok.text.endswith(".")
                    and nxt.token_type == TokenType.DOT
                    and adjacent(tok, nxt)
                ):
                    number = Token(
                        TokenType.NUMBER,
                        tok.text[:-1],
                        line=tok.line,
                        col=tok.col,
                        start=tok.start,
                        end=tok.end - 1,
                        comments=tok.comments,
                    )
                    ddot = Token(
                        TokenType.DDOT,
                        "..",
                        line=nxt.line,
                        col=nxt.col,
                        start=tok.end,
                        end=nxt.end,
                        comments=nxt.comments,
                    )
                    result.append(number)
                    result.append(ddot)
                    i += 2
                    continue

                # Pattern 2: DOT immediately followed by DOT -> DDOT
                if (
                    nxt is not None
                    and tok.token_type == TokenType.DOT
                    and nxt.token_type == TokenType.DOT
                    and adjacent(tok, nxt)
                ):
                    ddot = Token(
                        TokenType.DDOT,
                        "..",
                        line=tok.line,
                        col=tok.col,
                        start=tok.start,
                        end=nxt.end,
                        comments=tok.comments,
                    )
                    result.append(ddot)
                    i += 2
                    continue

                result.append(tok)
                i += 1

            return result

    Generator = Generator
    Parser = Parser

plpgsql = PlPgSQL
