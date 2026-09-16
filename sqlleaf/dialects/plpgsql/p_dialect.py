from __future__ import annotations

from sqlglot.dialects.postgres import Postgres
from sqlglot.tokens import Token

from sqlleaf.dialects.plpgsql.p_generator import PlPgSQLGenerator
from sqlleaf.dialects.plpgsql.p_parser import PlPgSQLParser
from sqlleaf.dialects.plpgsql.p_tokenizer import PLPGSQL_KEYWORD_TOKEN_NAMES, TokenType


class PlPgSQL(Postgres):
    """
    A custom dialect that extends Postgres to parse PL/pgSQL.
    """
    class Tokenizer(Postgres.Tokenizer):
        KEYWORDS = {
            **Postgres.Tokenizer.KEYWORDS,
            **{keyword: getattr(TokenType, keyword) for keyword in PLPGSQL_KEYWORD_TOKEN_NAMES},
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

                # Pattern 0: LABEL full pattern << id >>
                # Merge only when we see LT LT <identifier-like> GT GT with strict adjacency
                if (
                    i + 4 < n
                    and tok.token_type == TokenType.LT
                    and nxt is not None and nxt.token_type == TokenType.LT and adjacent(tok, nxt)
                ):
                    ident_tok = tokens[i + 2]
                    gt1 = tokens[i + 3]
                    gt2 = tokens[i + 4]

                    if (
                        ident_tok is not None
                        and ident_tok.text
                        and (ident_tok.text[0].isalpha() or ident_tok.text[0] == "_")
                        and all(ch.isalnum() or ch == "_" for ch in ident_tok.text)
                        and gt1.token_type == TokenType.GT
                        and gt2.token_type == TokenType.GT
                        and adjacent(nxt, ident_tok)
                        and adjacent(ident_tok, gt1)
                        and adjacent(gt1, gt2)
                    ):
                        # Create LABEL_BEGIN spanning the two '<'
                        lbegin = Token(
                            TokenType.LABEL_BEGIN,
                            "<<",
                            line=tok.line,
                            col=tok.col,
                            start=tok.start,
                            end=nxt.end,
                            comments=tok.comments,
                        )
                        # Keep the identifier token as-is
                        # Create LABEL_END spanning the two '>'
                        lend = Token(
                            TokenType.LABEL_END,
                            ">>",
                            line=gt1.line,
                            col=gt1.col,
                            start=gt1.start,
                            end=gt2.end,
                            comments=gt1.comments,
                        )
                        result.append(lbegin)
                        result.append(ident_tok)
                        result.append(lend)
                        i += 5
                        continue

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

    Generator = PlPgSQLGenerator
    Parser = PlPgSQLParser

plpgsql = PlPgSQL
