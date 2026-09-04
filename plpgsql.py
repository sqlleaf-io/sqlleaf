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
    # Optionally includes a DECLARE section captured as `declare`.
    arg_types = {"expressions": False, "begin": False, "declare": False}


class PGDeclare(exp.Expression):
    """A PL/pgSQL DECLARE section containing declaration items."""

    arg_types = {"expressions": True}


class PGDeclareItem(exp.Expression):
    """A single variable declaration inside a PL/pgSQL DECLARE section.

    Currently supports:
      - name type;
      - name type := expression;
    """

    arg_types = {
        "this": True,
        "kind": False,
        "expression": False,
        "value": False,
        "default": False,
        "assign": False,
        "constant": False,
        "collate": False,
        "not_null": False,
        "alias_for": False,
    }


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

    class Parser(PostgresParser):
        STATEMENT_PARSERS = {
            **PostgresParser.STATEMENT_PARSERS,
            TokenType.BEGIN: lambda self: self._parse_plpgsql_block(),
            TokenType.DECLARE: lambda self: self._parse_plpgsql_block(),
        }

        def _parse_plpgsql_block(self) -> PGBlock:
            # Determine entry: dispatcher consumed the first keyword into _prev
            declare = None
            if self._prev and self._prev.token_type == TokenType.DECLARE:
                # Started with DECLARE: parse declaration section, then require BEGIN
                declare = self._parse_pldeclare()
                if not self._match(TokenType.BEGIN):
                    self.raise_error("Expected BEGIN after DECLARE or at block start")
            else:
                # Started with BEGIN: already consumed, do nothing here
                pass

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

            return self.expression(PGBlock(expressions=expressions, declare=declare, begin=True))

        def _parse_pldeclare(self) -> PGDeclare:
            items: list[exp.Expression] = []
            while True:
                # If current chunk is consumed, move to the next one
                if self._index >= self._tokens_size:
                    self._advance_chunk()

                # Stop if the next significant token is BEGIN (start of block body)
                if not self._curr or self._match(TokenType.BEGIN, advance=False):
                    break

                item = self._parse_pldeclareitem()
                if not item:
                    break
                items.append(item)

                # After parsing an item, the chunk should be consumed (terminated by ';')
                if self._index < self._tokens_size:
                    self.raise_error("Invalid DECLARE item / Unexpected token")

                # Proceed to next chunk for the following declaration or BEGIN
                self.check_errors()
                self._advance_chunk()

            return self.expression(PGDeclare(expressions=items))

        def _parse_pldeclareitem(self) -> PGDeclareItem | None:
            ident = self._parse_id_var()
            if not ident:
                return None

            # Optional CONSTANT modifier
            is_constant = self._match_texts("CONSTANT")

            # Optional ALIAS FOR $n variant: must come before type parsing
            if self._match_text_seq("ALIAS", "FOR"):
                # Parse a positional parameter like $1
                param_expr = self._parse_identifier()
                return self.expression(
                    PGDeclareItem(
                        this=ident,
                        alias_for=True,
                        expression=param_expr,
                        value=param_expr,
                        constant=is_constant,
                    )
                )

            # Parse a type expression (prefer singular _parse_type, fallback to plural helper)
            type_expr = self._parse_type() or self._parse_types()

            # Optional COLLATE clause after type
            collate_expr = None
            if self._match(TokenType.COLLATE):
                # Collation can be an identifier or quoted identifier
                collate_expr = self._parse_id_var()

            # Optional NOT NULL constraint (sits after COLLATE and before DEFAULT)
            not_null = False
            if self._match_text_seq("NOT", "NULL"):
                not_null = True

            # Optional initialization with DEFAULT or assignment (:= or =)
            init_expr = None
            is_default = False
            assign_op: str | None = None
            if self._match(TokenType.DEFAULT):
                is_default = True
                init_expr = self._parse_bitwise()
            elif self._match(TokenType.COLON_EQ):
                assign_op = ":="
                init_expr = self._parse_bitwise()
            elif self._match(TokenType.EQ):
                assign_op = "="
                init_expr = self._parse_bitwise()

            return self.expression(
                PGDeclareItem(
                    this=ident,
                    kind=type_expr,
                    collate=collate_expr,
                    not_null=not_null,
                    expression=init_expr,
                    value=init_expr,
                    default=is_default,
                    assign=assign_op,
                    constant=is_constant,
                )
            )

    class Generator(PostgresGenerator):
        # Provide explicit transform to ensure support for PGBlock
        TRANSFORMS = {
            **getattr(PostgresGenerator, "TRANSFORMS", {}),
            PGBlock: lambda self, e: self.pgblock_sql(e),
            PGDeclare: lambda self, e: self.pldeclare_sql(e),
            PGDeclareItem: lambda self, e: self.pldeclareitem_sql(e),
        }

        # Also expose the auto-discovered method
        def pgblock_sql(self, expression: PGBlock) -> str:
            parts: list[str] = []

            # Render DECLARE section first if present
            declare = expression.args.get("declare")
            if declare and getattr(declare, "expressions", None):
                parts.append(self.sql(declare))

            parts.append("BEGIN")
            for expr in expression.expressions:
                parts.append(f"{self.sql(expr)};")
            parts.append("END")
            return " ".join(parts)

        def pldeclare_sql(self, expression: PGDeclare) -> str:
            items = [f"{self.sql(item)};" for item in expression.expressions]
            if not items:
                return "DECLARE"
            return " ".join(["DECLARE", *items])

        def pldeclareitem_sql(self, expression: PGDeclareItem) -> str:
            name = self.sql(expression.this)
            # Handle alias variant early: name ALIAS FOR $n
            if expression.args.get("alias_for"):
                target = self.sql(expression.args.get("expression"))
                return f"{name} ALIAS FOR {target}"
            typ = self.sql(expression.args.get("kind")) if expression.args.get("kind") is not None else ""
            # Normalize type rendering to uppercase to match Postgres style in tests
            typ_render = typ.upper() if typ else ""
            const_kw = " CONSTANT" if expression.args.get("constant") else ""
            collate = expression.args.get("collate")
            collate_sql = f" COLLATE {self.sql(collate)}" if collate is not None else ""
            not_null_sql = " NOT NULL" if expression.args.get("not_null") else ""
            init = expression.args.get("expression")

            if init is not None and expression.args.get("default"):
                return f"{name}{const_kw} {typ_render}{collate_sql}{not_null_sql} DEFAULT {self.sql(init)}"

            if init is not None:
                op = expression.args.get("assign") or ":="
                return f"{name}{const_kw} {typ_render}{collate_sql}{not_null_sql} {op} {self.sql(init)}"

            return f"{name}{const_kw} {typ_render}{collate_sql}{not_null_sql}"


plpgsql = PlPgSQL
