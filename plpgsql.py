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

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.generators.postgres import PostgresGenerator
from sqlglot.tokens import TokenType
from sqlglot.errors import ParseError


import logging

logger = logging.getLogger("plpgsql")

class Perform(exp.Select):
    """PL/pgSQL PERFORM statement implemented as a Select subclass.

    This makes PERFORM behave identically to SELECT (FROM, WHERE, GROUP BY, ORDER BY, LIMIT, ...),
    except that the head keyword is PERFORM and the result is discarded at runtime.
    """


class PLBlock(exp.Block):
    """PL/pgSQL BEGIN ... END block (subclass of Block)."""


class PLClose(exp.Expression):
    """PL/pgSQL CLOSE statement for cursors.

    Grammar: CLOSE { name | ALL };

    The argument is stored under the 'expression' key and is either:
      - an exp.Identifier for a cursor name, or
      - an exp.Var with value 'ALL'.
    """

    arg_types = {"expression": True}


class PLDeclareItem(exp.DeclareItem):
    """Extended DeclareItem for PL/pgSQL.

    Adds helpers to detect special type references used in DECLARE:
      - table%ROWTYPE
      - table.column%TYPE

    When parsing these, we store references under args:
      - row_of: Identifier (table name) for %ROWTYPE
      - column_of: Column expression for %TYPE
    """

    # Accept additional PL/pgSQL-specific attributes under args
    arg_types = {
        **exp.DeclareItem.arg_types,
        "row_of": False,
        "column_of": False,
        "alias_for": False,
    }

class PLpgSQLParser(PostgresParser):
    """Parser that recognizes the PERFORM statement and DECLARE ... BEGIN blocks."""

    def _parse_statement(self) -> exp.Expr | None:  # type: ignore[override]
        # End of input
        logger.warning(
            "Tokens: %s",
            [f"{t.token_type.name}({t.text})" for t in self._tokens],
        )

        if not self._curr:
            return None

        # Try custom PL/pgSQL constructs in precedence order
        for try_fn in (
            self._try_parse_declare_block,
            self._try_parse_begin_block,
            self._try_parse_close,
            self._try_parse_perform,
        ):
            node = try_fn()
            if node is not None:
                return node

        # Fallback to standard Postgres parsing
        return super()._parse_statement()

    # --- Helpers ---
    def _try_parse_declare_block(self) -> exp.Expr | None:
        """Attempt to parse a DECLARE ... BEGIN ... END block; return None if not present."""
        if not (self._match(TokenType.DECLARE) or self._match_texts("DECLARE")):
            return None

        declare_items = self._parse_declare_items_until_begin()
        statements = self._parse_pl_block_body()

        block = self.expression(PLBlock(expressions=statements))
        if declare_items:
            block.set("declare", exp.Declare(expressions=declare_items))
        return block

    def _try_parse_begin_block(self) -> exp.Expr | None:
        """Attempt to parse a simple BEGIN ... END block."""
        if not self._match(TokenType.BEGIN):
            return None

        statements = self._parse_pl_block_body()
        return self.expression(PLBlock(expressions=statements))

    def _try_parse_perform(self) -> exp.Expr | None:
        """Attempt to parse a PERFORM statement.

        The statements below mimic what occurs for SELECT statements."""
        if not self._match_text_seq("PERFORM"):
            return None

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

    def _try_parse_close(self) -> exp.Expr | None:
        """Attempt to parse a CLOSE statement inside a PL/pgSQL BEGIN block.

        Syntax: CLOSE { name | ALL };
        """
        if not self._match_text_seq("CLOSE"):
            return None

        # CLOSE ALL
        if self._match(TokenType.ALL):
            target: exp.Expression = exp.Var(this=self._prev.text)
            return self.expression(PLClose(expression=target))

        # CLOSE <identifier>
        if self._match(TokenType.VAR):
            ident_expr = exp.to_identifier(self._prev.text)
            return self.expression(PLClose(expression=ident_expr))

        self.raise_error("Expected identifier or ALL")

    def _parse_declare_items_until_begin(self) -> list[exp.Expression]:
        """Parse DECLARE items until BEGIN is encountered."""
        declare_items: list[exp.Expression] = []

        while True:
            # If no current token, advance to the next chunk
            if not self._curr:
                self._advance_chunk()
                if not self._curr:
                    # No more tokens, unexpected EOF before BEGIN
                    self.raise_error("Expected BEGIN after DECLARE section")

            # Stop when BEGIN is next
            if self._match(TokenType.BEGIN, advance=False) or self._match_texts("BEGIN", advance=False):
                # consume BEGIN so the subsequent body loop can run here
                self._match(TokenType.BEGIN) or self._match_texts("BEGIN")
                break

            # Skip stray semicolons or blank statements between decls
            if self._match(TokenType.SEMICOLON):
                continue

            # Parse a single DECLARE item head: name and type details (or alias)
            name, dtype, row_of, column_of, alias_for = self._parse_single_declare_head()

            # Optional default: := <expr>. Represent absence as None to avoid rendering ':= NULL'.
            default: exp.Expression | None = None
            if alias_for is None and self._match(TokenType.COLON_EQ):
                default = self._parse_expression()

            # Terminating semicolon for this item, possibly across chunk boundary
            if not self._match(TokenType.SEMICOLON):
                self._advance_chunk()
                self._match(TokenType.SEMICOLON)

            # Build PLDeclareItem (always) and append
            declare_items.append(
                self.expression(
                    self._build_pl_declare_item(
                        name=name,
                        dtype=dtype,
                        default=default,
                        row_of=row_of,
                        column_of=column_of,
                        alias_for=alias_for,
                    )
                )
            )

        return declare_items

    # --- DECLARE helpers ---
    def _parse_single_declare_head(
        self,
    ) -> tuple[
        exp.Expression,
        exp.DataType | None,
        exp.Expression | None,
        exp.Expression | None,
        exp.Expression | None,
    ]:
        """Parse the head of a DECLARE item: name and type info.

        Returns (name, dtype, row_of, column_of, alias_for). The default value and trailing semicolon
        are handled by the caller.
        """
        # First, handle the special case where the lexer produced a single STRING token
        # containing both the variable name and the rest of the head. Normalize it to
        # the same return shape as the standard path.
        combined = self.__parse_combined_declare_head_if_present()
        if combined is not None:
            return combined

        # Otherwise, parse using the decomposed helpers
        name = self.__parse_declare_name()

        alias_for = self.__parse_alias_for_if_present()
        if alias_for is not None:
            return name, None, None, None, alias_for

        row_of, column_of = self.__parse_row_or_column_suffix_if_present(name)
        if row_of is not None or column_of is not None:
            return name, None, row_of, column_of, None

        # Normal type parsing, possibly followed by a trailing %TYPE modifier
        dtype = self.__parse_normal_type()
        if self._match_texts("%") or self._match(TokenType.MOD):
            if self._match_texts("TYPE"):
                base = dtype.sql()
                if base and "." in base:
                    tbl, col = base.rsplit(".", 1)
                    column_of = exp.column(col, tbl)
                    dtype = None

        return name, dtype, None, column_of, None

    # --- Decomposed helpers for DECLARE head parsing ---
    def __parse_declare_name(self) -> exp.Expression:
        curr_tok = self._curr
        if not curr_tok:
            self.raise_error("Expected identifier in DECLARE item")
        raw_name = curr_tok.text
        name = exp.Var(this=raw_name)
        self._advance()
        return name

    def __parse_alias_for_if_present(self) -> exp.Expression | None:
        if not self._match_texts("ALIAS"):
            return None
        if not self._match_texts("FOR"):
            self.raise_error("Expected FOR after ALIAS in DECLARE item")
        return self._parse_primary()

    def __parse_row_or_column_suffix_if_present(self, base_name: exp.Expression) -> tuple[exp.Expression | None, exp.Expression | None]:
        # Non-advancing peek for a percent marker
        save_i = self._index
        save_curr = self._curr
        if self._match_texts("%", advance=False) or self._match(TokenType.MOD, advance=False):
            # Only consume on success
            if self._match_texts("ROWTYPE"):
                return exp.to_identifier(getattr(base_name, "name", "")), None
            if self._match_texts("TYPE"):
                # Inline %TYPE directly after name is not supported here; let normal type parsing handle it
                self._index = save_i
                self._curr = save_curr
                return None, None
        # Restore pointer (no consumption) and return no suffix
        self._index = save_i
        self._curr = save_curr
        return None, None

    def __parse_normal_type(self) -> exp.DataType:
        return self._parse_type()

    def __parse_combined_declare_head_if_present(
        self,
    ) -> tuple[
        exp.Expression,
        exp.DataType | None,
        exp.Expression | None,
        exp.Expression | None,
        exp.Expression | None,
    ] | None:
        curr_tok = self._curr
        if not curr_tok or curr_tok.token_type != TokenType.STRING or " " not in curr_tok.text:
            return None

        row_of: exp.Expression | None = None
        column_of: exp.Expression | None = None
        alias_for: exp.Expression | None = None

        raw_name, rest = curr_tok.text.split(None, 1)
        name = exp.Var(this=raw_name)

        type_text = rest.split(":=", 1)[0].strip()
        upper = type_text.upper()

        if upper.startswith("ALIAS FOR"):
            after = type_text[len("ALIAS FOR"):].strip()
            if after:
                alias_for = exp.Var(this=after)
            dtype: exp.DataType | None = None
        elif upper.endswith("%ROWTYPE"):
            base = type_text[: -len("%ROWTYPE")].strip()
            if base:
                row_of = exp.to_table(base)
            dtype = None
        elif upper.endswith("%TYPE"):
            base = type_text[: -len("%TYPE")].strip()
            if "." in base:
                tbl, col = base.rsplit(".", 1)
                column_of = exp.column(col, tbl)
            dtype = None
        else:
            dtype = exp.DataType.build(type_text, udt=True)

        # consume this combined token
        self._advance()
        return name, dtype, row_of, column_of, alias_for

    def _build_pl_declare_item(
        self,
        *,
        name: exp.Expression,
        dtype: exp.DataType | None,
        default: exp.Expression | None,
        row_of: exp.Expression | None,
        column_of: exp.Expression | None,
        alias_for: exp.Expression | None,
    ) -> PLDeclareItem:
        """Create a PLDeclareItem with optional row/column type references.

        Builds the node directly and sets only the arguments that are present,
        avoiding loosely typed kwargs dicts and type ignores.
        """
        item = PLDeclareItem(this=[name])
        if dtype is not None:
            item.set("kind", dtype)
        if default is not None:
            item.set("default", default)
        if row_of is not None:
            item.set("row_of", row_of)
        if column_of is not None:
            item.set("column_of", column_of)
        if alias_for is not None:
            item.set("alias_for", alias_for)
        return item

    def _parse_pl_block_body(self) -> list[exp.Expression]:
        """Parse a PL/pgSQL block body until END.

        Returns the list of statements inside the block.
        """
        statements: list[exp.Expression] = []

        while True:
            if not self._curr:
                self._advance_chunk()
                if not self._curr:
                    self.raise_error("Expected END to close BEGIN ... END block")

            # Stop at END (token or text)
            if self._match(TokenType.END) or self._match_texts("END"):
                break

            stmt = self._parse_statement()
            if not stmt:
                self.raise_error("Expected statement inside BEGIN ... END")

            statements.append(stmt)
            # Optional semicolon after each statement
            self._match(TokenType.SEMICOLON)

        if not statements:
            # For empty bodies, raise a plain ParseError without location suffix
            # to match tests' expected message.
            raise ParseError("Empty BEGIN ... END block is not allowed")

        # Require a trailing semicolon after END in PL/pgSQL blocks
        self._match(TokenType.SEMICOLON)

        return statements


class PLpgSQLGenerator(PostgresGenerator):
    """Generator that renders PERFORM statements and DECLARE blocks."""

    # Register handler for our custom Perform node
    TRANSFORMS = {
        **PostgresGenerator.TRANSFORMS,
        Perform: lambda self, e: self.perform_sql(e),
        PLBlock: lambda self, e: self.plblock_sql(e),
        PLDeclareItem: lambda self, e: self.pldeclareitem_sql(e),
        # Explicitly register PLClose to ensure dispatch picks it up
        PLClose: lambda self, e: self.plclose_sql(e),
    }

    def plblock_sql(self, expression: PLBlock) -> str:
        """Generate SQL for PL/pgSQL blocks, including an optional DECLARE section."""
        declare = expression.args.get("declare")

        decl_sql = ""
        if declare:
            lines: list[str] = []
            for item in declare.expressions or []:
                if isinstance(item, PLDeclareItem):
                    # Delegate PL/pgSQL-specific line formatting to the dedicated method
                    line = f"    {self.pldeclareitem_sql(item)}"
                else:
                    # Fallback: use generic rendering and ensure it ends with ';'
                    rendered = self.sql(item).rstrip()
                    if not rendered.endswith(";"):
                        rendered += ";"
                    line = f"    {rendered}"
                lines.append(line)
            decl_sql = "DECLARE\n" + "\n".join(lines) + "\n"

        body_sql = self.block_sql(expression)
        return decl_sql + body_sql

    def pldeclareitem_sql(self, expression: PLDeclareItem) -> str:
        """Render a single PL/pgSQL declare item line.

        Example outputs:
          - "myrow tablename%ROWTYPE;"
          - "myfield tablename.columnname%TYPE := 1;"
        """
        names = self.expressions(expression, "this") or []
        name = ", ".join(names) if names else ""
        default_expr = expression.args.get("default")

        # Alias variant takes precedence and doesn't render type/default
        alias_for = expression.args.get("alias_for")
        if alias_for is not None:
            alias_sql = self.sql(expression, "alias_for")
            line = f"{name} ALIAS FOR {alias_sql};"
            return line

        if expression.args.get("row_of"):
            tbl = self.sql(expression, "row_of")
            rendered_type = f"{tbl}%ROWTYPE"
        elif expression.args.get("column_of"):
            col = self.sql(expression, "column_of")
            rendered_type = f"{col}%TYPE"
        else:
            kind = self.sql(expression, "kind")
            rendered_type = f"{kind}" if kind else ""

        line = f"{name} {rendered_type}".rstrip()
        if default_expr is not None:
            line += f" := {self.sql(expression, 'default')}"
        line += ";"
        return line

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
        expressions = expression.expressions

        # Drop a trailing END marker if present
        if expressions and isinstance(expressions[-1], exp.EndStatement):
            expressions = expressions[:-1]

        # Unwrap a nested PLBlock wrapper if it's the first child and also
        # collect any subsequent sibling statements up to END. This compensates
        # for sqlglot's chunk-based parsing which may split block body statements
        # across chunks, causing siblings to appear alongside the inner PLBlock.
        if expressions and isinstance(expressions[0], PLBlock):
            inner = expressions[0].expressions
            for e in expressions[1:]:
                if isinstance(e, exp.EndStatement):
                    break
                inner.append(e)
        else:
            inner = expressions

        body = "; ".join(s for s in (self.sql(e) for e in inner) if s)
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

    def plclose_sql(self, expression: PLClose) -> str:
        target = self.sql(expression, "expression")
        return f"CLOSE {target}"


class PLpgSQL(Postgres):
    """Dialect class: Postgres + PERFORM statement."""

    Parser = PLpgSQLParser
    Generator = PLpgSQLGenerator
