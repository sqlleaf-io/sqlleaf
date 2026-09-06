from __future__ import annotations

"""
Example custom dialect that extends Postgres to parse simple PL/pgSQL-style blocks.
"""

from sqlglot import exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.generators.postgres import PostgresGenerator
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import TokenType


class PGBlock(exp.Expression):
    """A Postgres-specific BEGIN ... END block.
    """
    arg_types = {"expressions": False, "begin": False, "declare": False, "exception": False}


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


class PGException(exp.Expression):
    """PL/pgSQL EXCEPTION section containing WHEN entries.

    Mirror exp.Case by storing WHEN clauses under `ifs`.
    """
    arg_types = {"ifs": True}


class PGWhen(exp.Expression):
    """A single WHEN ... THEN ... entry inside an EXCEPTION section."""
    arg_types = {"condition": True, "then": True}


class PGOthers(exp.Expression):
    """Represents the OTHERS keyword in EXCEPTION WHEN OTHERS THEN ..."""
    arg_types = {"this": False}


class PGLoop(exp.Expression):
    """A PL/pgSQL LOOP ... END LOOP construct.
    """
    arg_types = {"expressions": True}


class PGWhile(exp.Expression):
    """A PL/pgSQL WHILE statement..

    Syntax:
        WHILE ... LOOP ... END LOOP [label]
    """
    arg_types = {"this": True, "expressions": True, "label": False}


class PGExit(exp.Expression):
    """A PL/pgSQL EXIT statement.

    Syntax:
      EXIT [ label ] [ WHEN <expression> ];
    """
    arg_types = {"this": False, "when": False}


class PGContinue(exp.Expression):
    """A PL/pgSQL CONTINUE statement.

    Syntax:
      CONTINUE [ label ] [ WHEN <expression> ];
    """
    arg_types = {"this": False, "when": False}


class PGRaise(exp.Expression):
    """A PL/pgSQL RAISE statement.

    Supports the following variants:

      - RAISE [ level ] 'format' [, expression [, ... ]] [ USING option { = | := } expression [, ...] ];
      - RAISE [ level ] condition_name [ USING option { = | := } expression [, ...] ];
      - RAISE [ level ] SQLSTATE 'sqlstate' [ USING option { = | := } expression [, ...] ];
      - RAISE [ level ] USING option { = | := } expression [, ... ];
      - RAISE ;  (re-raise inside EXCEPTION handler)

    Fields:
      - level: optional exp.Identifier
      - message: optional exp.Expression (typically a string literal)
      - expressions: optional CSV expressions used to fill format placeholders
      - condition: optional exp.Identifier (condition name)
      - sqlstate: optional PGSqlState
      - using: optional list of AssignArg entries
    """

    arg_types = {
        "level": False,
        "message": False,
        "expressions": False,
        "condition": False,
        "sqlstate": False,
        "using": False,
    }


class PGAssert(exp.Expression):
    """A PL/pgSQL ASSERT statement.

    Syntax:
      ASSERT condition [ , message ];
    """

    arg_types = {"condition": True, "message": False}


class AssignArg(exp.Expression, exp.Binary):
    """Represents a named argument using the PL/pgSQL ``:=`` syntax.

    Example: ``key := 42``
    """
    pass


class PGOpenCursor(exp.Expression):
    """A PL/pgSQL OPEN cursor statement.

    Supports two forms:
      - Unbound: OPEN cursorvar [ [ NO ] SCROLL ] FOR query;
      - Bound:   OPEN cursorvar [ ( arg_value [, ...] ) ];
    """
    arg_types = {"this": True, "expression": False, "scroll": False, "expressions": False}


class PGFetch(exp.Expression):
    """A PL/pgSQL FETCH statement.

    Syntax:
      FETCH [ direction { FROM | IN } ] <cursor> INTO <target> [, <target> ...];
    """
    arg_types = {
        "this": True,
        "expressions": True,
        "direction": False,
        "preposition": False,
    }


class PGMove(exp.Expression):
    """A PL/pgSQL MOVE statement.

    Syntax:
      MOVE [ direction { FROM | IN } ] <cursor>;
    """
    arg_types = {
        "this": True,
        "direction": False,
        "preposition": False,
    }


class PGClose(exp.Expression):
    """A PL/pgSQL CLOSE cursor statement.

    Syntax:
      CLOSE <cursor>;
    """
    arg_types = {"this": True}


class PGNext(exp.Expression):
    """FETCH NEXT direction."""
    arg_types = {"this": False}


class PGPrior(exp.Expression):
    """FETCH PRIOR direction."""
    arg_types = {"this": False}


class PGFirst(exp.Expression):
    """FETCH FIRST direction."""
    arg_types = {"this": False}


class PGLast(exp.Expression):
    """FETCH LAST direction."""
    arg_types = {"this": False}


class PGForward(exp.Expression):
    """FETCH FORWARD direction."""
    arg_types = {"this": False, "all": False}


class PGBackward(exp.Expression):
    """FETCH BACKWARD direction."""
    arg_types = {"this": False, "all": False}


class PGAbsolute(exp.Expression):
    """FETCH ABSOLUTE <count> direction."""
    arg_types = {"this": True}


class PGRelative(exp.Expression):
    """FETCH RELATIVE <count> direction."""
    arg_types = {"this": True}


class PGAll(exp.Expression):
    """Direction variant representing ALL (no additional keyword).

    Used for forms like "FETCH ALL FROM c" or as the payload of FORWARD/BACKWARD ALL.
    """
    arg_types = {"this": False}


class PGSqlState(exp.Expression):
    """Represents the SQLSTATE condition, optionally followed by a string literal."""
    arg_types = {"this": False}


class PGReturn(exp.Expression):
    """Represents a PL/pgSQL RETURN statement.

    Supports both forms:
      - RETURN;
      - RETURN <expression>;
      - RETURN QUERY <query>;

    The optional expression is stored in `this`.
    For RETURN QUERY, the returned query is stored in `expression`, and a boolean flag
    `query` is set to True.
    For RETURN NEXT, the returned expression is stored in `expression`, and a boolean flag
    `next` is set to True.
    """

    arg_types = {"this": False, "query": False, "next": False}


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

        # In base sqlglot, FETCH is treated as a COMMAND, which swallows the rest
        # of the statement as a single STRING token. For PL/pgSQL we want to
        # parse FETCH <cursor> INTO <targets> normally, so exclude FETCH from
        # the COMMANDS set.
        COMMANDS = Postgres.Tokenizer.COMMANDS - {TokenType.FETCH}

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

            expressions: list[exp.Expression] = []
            exception = None

            while True:
                # If we've consumed the current chunk, move to the next one
                if self._index >= self._tokens_size:
                    self._advance_chunk()

                # Stop if we reached END (block terminator)
                if not self._curr:
                    break

                # Detect start of EXCEPTION section (structural, not delimited by ';')
                if self._match_texts("EXCEPTION", advance=False):
                    # Parse the exception section and then let the loop continue
                    # so that END is handled by the usual logic.
                    exception = self._parse_pgexception()
                    # After parsing EXCEPTION, do not parse more statements here.
                    # Continue to let the END be consumed by the block logic.
                    continue

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

            return self.expression(PGBlock(expressions=expressions, declare=declare, exception=exception, begin=True))

        def _parse_pgexception(self) -> exp.Expression:
            # Consume EXCEPTION keyword if not yet consumed
            if not self._match_texts("EXCEPTION"):
                self.raise_error("Expected EXCEPTION in block")

            whens: list[exp.Expression] = []

            # Parse one or more WHEN clauses
            while self._match(TokenType.WHEN, advance=False):
                whens.append(self._parse_pgwhen())

            if not whens:
                self.raise_error("EXCEPTION requires at least one WHEN clause")

            return self.expression(PGException(ifs=whens))

        def _parse_pgwhen(self) -> exp.Expression:
            if not self._match(TokenType.WHEN):
                self.raise_error("Expected WHEN in EXCEPTION section")

            # Parse one or more condition identifiers separated by OR
            conditions: list[exp.Expression] = []

            # First condition (identifier or SQLSTATE 'xxxxx')
            cond = self._parse_pgwhen_condition()
            if cond is not None:
                conditions.append(cond)

            # Additional conditions joined by OR
            while self._match(TokenType.OR):
                more = self._parse_pgwhen_condition()
                if more is None:
                    self.raise_error("Expected condition after OR")
                conditions.append(more)

            if not conditions:
                self.raise_error("WHEN requires at least one condition")

            if not self._match(TokenType.THEN):
                self.raise_error("Expected THEN in WHEN clause")

            # Parse one or more statements until next WHEN or END
            body: list[exp.Expression] = []
            while True:
                if not self._curr:
                    break

                # Stop if new WHEN or END is next
                if self._match(TokenType.WHEN, advance=False) or self._match(TokenType.END, advance=False):
                    break

                stmt = self._parse_statement()
                if stmt is not None:
                    body.append(stmt)

                # Ensure the statement consumed the whole chunk (terminated by ';')
                if self._index < self._tokens_size:
                    self.raise_error("Invalid expression in WHEN body / Unexpected token")

                self.check_errors()
                self._advance_chunk()

            if not body:
                self.raise_error("WHEN body requires at least one statement")

            # Combine multiple conditions into a single OR expression like exp.Case does
            condition_expr = conditions[0]
            if len(conditions) > 1:
                # Use builder to combine with OR respecting nesting
                condition_expr = exp.or_(*conditions)

            return self.expression(PGWhen(condition=condition_expr, then=body))

        def _parse_pgwhen_condition(self) -> exp.Expression | None:
            # Support: identifier condition (e.g., division_by_zero)
            # the keyword OTHERS, or the form: SQLSTATE ['XXXXX']
            if self._match_texts("OTHERS"):
                return self.expression(PGOthers())

            if self._match_texts("SQLSTATE"):
                # If a quoted literal follows, parse and attach it.
                if self._match(TokenType.STRING, advance=False):
                    lit = self._parse_primary()
                    if isinstance(lit, exp.Literal) and lit.is_string:
                        return self.expression(PGSqlState(this=lit))

                self.raise_error("SQLSTATE must be followed by a quoted literal")

            return self._parse_id_var()

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

        def _parse_statement(self) -> exp.Expr | None:
            # Let RETURN be handled as a regular statement within this dialect
            if self._curr and self._curr.text.upper() == "RETURN":
                return self._parse_pgreturn()
            # Support WHILE ... LOOP ... END LOOP
            if self._curr and self._curr.text.upper() == "WHILE":
                return self._parse_pgwhile()
            # Support top-level LOOP statements within blocks and WHEN bodies
            if self._curr and self._curr.text.upper() == "LOOP":
                return self._parse_pgloop()
            # Support EXIT [label] [WHEN expr]
            if self._curr and self._curr.text.upper() == "EXIT":
                return self._parse_pgexit()
            # Support CONTINUE [label] [WHEN expr]; anywhere similar to EXIT
            if self._curr and self._curr.text.upper() == "CONTINUE":
                return self._parse_pgcontinue()
            # Support RAISE statement and its variants
            if self._curr and self._curr.text.upper() == "RAISE":
                return self._parse_pgraise()
            # Support ASSERT condition [, message]; anywhere
            if self._curr and self._curr.text.upper() == "ASSERT":
                return self._parse_pgassert()
            # Support OPEN cursorvar [ [ NO ] SCROLL ] FOR query; anywhere
            if self._curr and self._curr.text.upper() == "OPEN":
                return self._parse_pgopen()
            # Support FETCH cursor INTO targets; anywhere
            if self._curr and self._curr.text.upper() == "FETCH":
                return self._parse_pgfetch()
            # Support MOVE [direction { FROM | IN }] cursor; anywhere
            if self._curr and self._curr.text.upper() == "MOVE":
                return self._parse_pgmove()
            # Support CLOSE cursor; anywhere
            if self._curr and self._curr.text.upper() == "CLOSE":
                return self._parse_pgclose()
            return super()._parse_statement()

        def _parse_pgwhile(self) -> PGWhile:
            # Consume WHILE keyword
            if not self._match_texts("WHILE"):
                self.raise_error("Expected WHILE")

            # Parse condition expression
            cond = self._parse_expression()

            # Guard against accidental aliasing like: <cond> AS LOOP
            if isinstance(cond, exp.Alias):
                alias = cond.args.get("alias")
                if isinstance(alias, exp.Identifier) and alias.name.upper() == "LOOP":
                    cond = cond.this
                else:
                    # Require LOOP explicitly after condition if not via alias
                    if not self._match_texts("LOOP"):
                        self.raise_error("Expected LOOP after WHILE condition")
            else:
                if not self._match_texts("LOOP"):
                    self.raise_error("Expected LOOP after WHILE condition")

            # Parse body statements until END
            body: list[exp.Expression] = []
            while True:
                if self._match(TokenType.END):
                    break

                stmt = self._parse_statement()
                body.append(stmt)
                # Statements in PL/pgSQL blocks are chunk-delimited; advance to next chunk
                self._advance_chunk()

            # After END, require LOOP
            if not self._match_texts("LOOP"):
                self.raise_error("Expected LOOP after END in WHILE block")

            # Optional label and optional semicolon
            label = self._parse_id_var(any_token=True)
            self._match(TokenType.SEMICOLON)

            return self.expression(PGWhile(this=cond, expressions=body, label=label))

        def _parse_pgassert(self) -> PGAssert:
            # Consume ASSERT keyword
            if not self._match_texts("ASSERT"):
                self.raise_error("Expected ASSERT")

            condition = self._parse_expression()

            message = None
            if self._match(TokenType.COMMA):
                message = self._parse_expression()

            return self.expression(PGAssert(condition=condition, message=message))

        def _parse_pgraise(self) -> PGRaise:
            # Consume RAISE keyword
            if not self._match_texts("RAISE"):
                self.raise_error("Expected RAISE")

            LEVELS = {"DEBUG", "LOG", "INFO", "NOTICE", "WARNING", "EXCEPTION"}

            level = None
            message: exp.Expression | None = None
            fmt_args: list[exp.Expression] | None = None
            condition = None
            sqlstate: exp.Expression | None = None
            using_args: list[exp.Expression] | None = None

            # Optional level
            if self._curr is not None and self._curr.text.upper() in LEVELS:
                # Treat as identifier to keep minimal AST
                token = self._curr
                self._advance()
                ident = exp.to_identifier(token.text)
                ident.update_positions(token)
                level = ident

            # Helper to parse USING options into AssignArg entries
            def _parse_using_list() -> list[exp.Expression]:
                # Current token should be USING (not yet consumed)
                if not self._match(TokenType.USING):
                    return []
                opts: list[exp.Expression] = []
                # Parse CSV of name {:=|=} expr
                first = True
                while True:
                    # Name is a simple identifier or variable token
                    name = self._parse_id_var(any_token=True)
                    if not name:
                        if first:
                            self.raise_error("Expected option name after USING")
                        break

                    # Allow either := or =
                    if self._match(TokenType.COLON_EQ) or self._match(TokenType.EQ):
                        value = self._parse_expression()
                        opts.append(AssignArg(this=name, expression=value))
                    else:
                        self.raise_error("Expected ':=' or '=' in USING option")

                    first = False
                    if not self._match(TokenType.COMMA):
                        break

                return opts

            # Branch on next token for main payload
            if self._curr is None or self._index >= self._tokens_size:
                # Bare re-raise
                pass
            elif self._match_texts("SQLSTATE"):
                # Expect a quoted literal next
                if self._match(TokenType.STRING, advance=False):
                    lit = self._parse_primary()
                    if isinstance(lit, exp.Literal) and lit.is_string:
                        sqlstate = self.expression(PGSqlState(this=lit))
                    else:
                        self.raise_error("SQLSTATE must be followed by a quoted literal")
                else:
                    self.raise_error("SQLSTATE must be followed by a quoted literal")
            elif self._match(TokenType.STRING, advance=False):
                # Message/format expression (typically a string)
                message = self._parse_expression()
                # Optional CSV of expressions
                args: list[exp.Expression] = []
                while self._match(TokenType.COMMA):
                    args.append(self._parse_expression())
                if args:
                    fmt_args = args
            elif self._match(TokenType.USING, advance=False):
                # USING-only form
                using_args = _parse_using_list()
            else:
                # Condition name (identifier)
                condition = self._parse_id_var(any_token=True)

            # Optional USING after message/condition/sqlstate
            if using_args is None and self._match(TokenType.USING, advance=False):
                using_args = _parse_using_list()

            return self.expression(
                PGRaise(
                    level=level,
                    message=message,
                    expressions=fmt_args,
                    condition=condition,
                    sqlstate=sqlstate,
                    using=using_args,
                )
            )

        def _parse_pgreturn(self) -> PGReturn:
            # Consume RETURN keyword
            if not self._match_texts("RETURN"):
                self.raise_error("Expected RETURN")

            # Support RETURN QUERY <query>;
            if self._match_texts("QUERY"):
                # Parse a full statement that returns rows (eg. SELECT ...)
                # We delegate to the standard statement parser so it can handle
                # SELECT, WITH, VALUES, INSERT ... RETURNING, etc.
                query = self._parse_statement()
                if query is None:
                    self.raise_error("Expected query after RETURN QUERY")
                return self.expression(PGReturn(this=query, query=True))

            # Support RETURN NEXT <expression>;
            if self._match_texts("NEXT"):
                # NEXT must be followed by an expression on the same chunk
                if self._curr is None or self._index >= self._tokens_size:
                    self.raise_error("Expected expression after RETURN NEXT")
                expr = self._parse_expression()
                return self.expression(PGReturn(this=expr, next=True))

            # Otherwise, optional expression on the same chunk before semicolon.
            # If end of chunk reached immediately, it's a bare RETURN.
            expr: exp.Expression | None = None
            if self._curr is not None and self._index < self._tokens_size:
                expr = self._parse_expression()

            return self.expression(PGReturn(this=expr))

        def _parse_pgloop(self) -> PGLoop:
            # Consume LOOP keyword starting the construct
            if not self._match_texts("LOOP"):
                self.raise_error("Expected LOOP")

            body: list[exp.Expression] = []

            while True:
                # Move to next chunk when the current is fully consumed
                if self._index >= self._tokens_size:
                    self._advance_chunk()

                # If next token begins END, close the loop
                if self._match(TokenType.END, advance=False):
                    self._advance()  # consume END
                    # Require the LOOP keyword after END
                    if not self._match_texts("LOOP"):
                        self.raise_error("Expected LOOP after END in LOOP block")
                    break

                if not self._curr:
                    break

                stmt = self._parse_statement()
                if stmt is not None:
                    body.append(stmt)

                # Ensure full chunk consumption for each statement
                if self._index < self._tokens_size:
                    self.raise_error("Invalid expression inside LOOP / Unexpected token")

                self.check_errors()
                self._advance_chunk()

            return self.expression(PGLoop(expressions=body))

        def _parse_pgexit(self) -> PGExit:
            # Consume EXIT keyword
            if not self._match_texts("EXIT"):
                self.raise_error("Expected EXIT")

            label = None
            condition = None

            # Optional label: next token is an identifier/var (and not WHEN)
            if self._curr is not None and self._curr.text.upper() != "WHEN":
                label = self._parse_id_var()

            # Optional WHEN <expression>
            if self._match(TokenType.WHEN):
                condition = self._parse_expression()

            return self.expression(PGExit(this=label, when=condition))

        def _parse_pgcontinue(self) -> PGContinue:
            # Consume CONTINUE keyword
            if not self._match_texts("CONTINUE"):
                self.raise_error("Expected CONTINUE")

            label = None
            condition = None

            # Optional label (if next token isn't WHEN)
            if self._curr is not None and self._curr.text.upper() != "WHEN":
                label = self._parse_id_var()

            # Optional WHEN <expression>
            if self._match(TokenType.WHEN):
                condition = self._parse_expression()

            return self.expression(PGContinue(this=label, when=condition))

        def _parse_open_args(self) -> list[exp.Expression]:
            """Parse an OPEN cursor argument list and return the collected args.

            Supports positional arguments, name := value (AssignArg), and
            name => value (Kwarg).

            Precondition: current token is '(' (not yet consumed).
            Postcondition: the closing ')' is consumed.
            """
            # Consume '('
            self._advance()

            # Delegate argument collection to helper (does not consume ')')
            args: list[exp.Expression] = []

            if not self._match(TokenType.R_PAREN, advance=False):
                while True:
                    # Parse an expression; if immediately followed by := or =>,
                    # treat the parsed expression as the name of a named argument.
                    first = self._parse_expression()
                    if self._match(TokenType.COLON_EQ) or self._match(TokenType.FARROW):
                        op_token = self._prev
                        value_expr = self._parse_expression()
                        if op_token and op_token.token_type == TokenType.COLON_EQ:
                            args.append(AssignArg(this=first, expression=value_expr))
                        else:
                            args.append(exp.Kwarg(this=first, expression=value_expr))
                    else:
                        args.append(first)

                    if not self._match(TokenType.COMMA):
                        break

            if not self._match(TokenType.R_PAREN):
                self.raise_error("Expected ')' to close argument list in OPEN")

            return args

        def _parse_pgopen(self) -> PGOpenCursor:
            # Consume OPEN keyword
            if not self._match_texts("OPEN"):
                self.raise_error("Expected OPEN")

            # Cursor variable identifier
            cursor = self._parse_id_var()

            # Bound cursor with arguments: OPEN c(<args>) where args can be positional,
            # name := value (AssignArg), or name => value (Kwarg)
            if self._match(TokenType.L_PAREN, advance=False):
                args = self._parse_open_args()
                return self.expression(PGOpenCursor(this=cursor, expressions=args))

            # Optional [[NO] SCROLL]
            scroll: bool | None = None
            if self._match_texts("NO"):
                if not self._match_texts("SCROLL"):
                    self.raise_error("Expected SCROLL after NO in OPEN")
                scroll = False
            elif self._match_texts("SCROLL"):
                scroll = True

            # If there's no FOR and no SCROLL/NO SCROLL, treat as bound cursor with zero args: OPEN c;
            if not self._match_texts("FOR"):
                if scroll is None:
                    return self.expression(PGOpenCursor(this=cursor))
                # If SCROLL/NO SCROLL was provided, FOR is required
                self.raise_error("Expected FOR in OPEN cursor statement")

            query = self._parse_statement()
            if query is None:
                self.raise_error("Expected query after OPEN ... FOR")

            return self.expression(PGOpenCursor(this=cursor, expression=query, scroll=scroll))

        def _parse_pgfetch(self) -> PGFetch:
            # Consume FETCH keyword
            if not self._match_texts("FETCH"):
                self.raise_error("Expected FETCH")

            # Parse optional direction, optional preposition (required when direction given), and cursor
            direction, preposition, cursor = self._parse_pg_direction_and_cursor(after_kw="FETCH")

            # INTO keyword
            if not self._match_texts("INTO"):
                self.raise_error("Expected INTO in FETCH statement")

            # One or more targets separated by commas on the same chunk
            targets = self._parse_csv(self._parse_expression)

            if not targets:
                self.raise_error("Expected target list after INTO in FETCH")

            return self.expression(
                PGFetch(
                    this=cursor,
                    expressions=targets,
                    direction=direction,
                    preposition=preposition,
                )
            )

        def _parse_pgmove(self) -> "PGMove":
            # Consume MOVE keyword
            if not self._match_texts("MOVE"):
                self.raise_error("Expected MOVE")

            # Parse optional direction, optional preposition (required when direction given), and cursor
            direction, preposition, cursor = self._parse_pg_direction_and_cursor(after_kw="MOVE")

            return self.expression(
                PGMove(
                    this=cursor,
                    direction=direction,
                    preposition=preposition,
                )
            )

        def _parse_pgclose(self) -> "PGClose":
            # Consume CLOSE keyword
            if not self._match_texts("CLOSE"):
                self.raise_error("Expected CLOSE")

            cursor = self._parse_id_var()
            return self.expression(PGClose(this=cursor))

        def _parse_pg_direction_and_cursor(
            self, *, after_kw: str
        ) -> tuple[exp.Expression | None, str | None, exp.Expression]:
            """Parse optional direction and required preposition (if direction present), then cursor name.

            Returns a tuple of (direction_expr_or_none, preposition_or_none, cursor_identifier_expr).
            The error messages incorporate the SQL keyword provided by ``after_kw`` for clarity.
            """
            direction: exp.Expression | None = None
            preposition: str | None = None

            def _parse_required_preposition(msg: str) -> str:
                if self._match_texts(("FROM", "IN")):
                    return (self._prev.text or "").upper()
                self.raise_error(msg)
                return ""

            SIMPLE_DIRS = {
                "NEXT": PGNext,
                "PRIOR": PGPrior,
                "FIRST": PGFirst,
                "LAST": PGLast,
            }

            # Helper: check if the upcoming token sequence represents a numeric count
            def _next_is_numeric() -> bool:
                return (
                    (self._curr is not None and self._curr.token_type == TokenType.NUMBER)
                    or (
                        self._curr is not None
                        and self._curr.token_type == TokenType.DASH
                        and self._next is not None
                        and self._next.token_type == TokenType.NUMBER
                    )
                )

            # Handle FORWARD/BACKWARD with optional count/ALL
            if self._match_texts(("FORWARD", "BACKWARD")):
                which = (self._prev.text or "").upper()
                # Optional ALL or count after FORWARD/BACKWARD
                if self._match_texts("ALL"):
                    direction = (
                        self.expression(PGForward(all=True))
                        if which == "FORWARD"
                        else self.expression(PGBackward(all=True))
                    )
                else:
                    # Parse numeric count only when the next token(s) are numeric
                    if _next_is_numeric():
                        count_expr = self._parse_bitwise()
                        direction = (
                            self.expression(PGForward(this=count_expr))
                            if which == "FORWARD"
                            else self.expression(PGBackward(this=count_expr))
                        )
                    else:
                        # No count provided; just the keyword
                        direction = (
                            self.expression(PGForward())
                            if which == "FORWARD"
                            else self.expression(PGBackward())
                        )

                preposition = _parse_required_preposition(
                    f"Expected FROM or IN after {after_kw} direction"
                )

            elif self._match_texts(tuple(SIMPLE_DIRS.keys())):
                kw = (self._prev.text or "").upper()
                direction = self.expression(SIMPLE_DIRS[kw]())
                preposition = _parse_required_preposition(
                    f"Expected FROM or IN after {after_kw} direction"
                )
            elif self._match_texts(("ABSOLUTE", "RELATIVE")):
                kind = (self._prev.text or "").upper()
                count_expr = self._parse_bitwise()
                direction = (
                    self.expression(PGAbsolute(this=count_expr))
                    if kind == "ABSOLUTE"
                    else self.expression(PGRelative(this=count_expr))
                )
                preposition = _parse_required_preposition(
                    f"Expected FROM or IN after {after_kw} ABSOLUTE/RELATIVE count"
                )

            else:
                # Standalone ALL or standalone count (equivalent to FORWARD ALL / FORWARD count)
                if self._match_texts("ALL"):
                    direction = self.expression(PGAll())
                    preposition = _parse_required_preposition(
                        f"Expected FROM or IN after {after_kw} ALL"
                    )
                else:
                    # Parse numeric count only when the next token(s) are numeric
                    if _next_is_numeric():
                        count_expr = self._parse_bitwise()
                        direction = count_expr
                        preposition = _parse_required_preposition(
                            f"Expected FROM or IN after {after_kw} count"
                        )

            cursor = self._parse_id_var()
            return direction, preposition, cursor

    class Generator(PostgresGenerator):
        # Provide explicit transform to ensure support for PGBlock
        TRANSFORMS = {
            **getattr(PostgresGenerator, "TRANSFORMS", {}),
            PGBlock: lambda self, e: self.pgblock_sql(e),
            PGDeclare: lambda self, e: self.pldeclare_sql(e),
            PGDeclareItem: lambda self, e: self.pldeclareitem_sql(e),
            PGException: lambda self, e: self.pgexception_sql(e),
            PGWhen: lambda self, e: self.pgwhen_sql(e),
            PGLoop: lambda self, e: self.pgloop_sql(e),
            PGWhile: lambda self, e: self.pgwhile_sql(e),
            PGReturn: lambda self, e: self.pgreturn_sql(e),
            PGExit: lambda self, e: self.pgexit_sql(e),
            PGContinue: lambda self, e: self.pgcontinue_sql(e),
            PGRaise: lambda self, e: self.pgraise_sql(e),
            AssignArg: lambda self, e: self.assignarg_sql(e),
            PGSqlState: lambda self, e: self.pgsqlstate_sql(e),
            PGOpenCursor: lambda self, e: self.pgopencursor_sql(e),
            PGFetch: lambda self, e: self.pgfetch_sql(e),
            PGMove: lambda self, e: self.pgmove_sql(e),
            PGClose: lambda self, e: self.pgclose_sql(e),
            PGNext: lambda self, e: self.pgnext_sql(e),
            PGPrior: lambda self, e: self.pgprior_sql(e),
            PGFirst: lambda self, e: self.pgfirst_sql(e),
            PGLast: lambda self, e: self.pglast_sql(e),
            PGForward: lambda self, e: self.pgforward_sql(e),
            PGBackward: lambda self, e: self.pgbackward_sql(e),
            PGAbsolute: lambda self, e: self.pgabsolute_sql(e),
            PGRelative: lambda self, e: self.pgrelative_sql(e),
            PGAll: lambda self, e: self.pgall_sql(e),
            PGAssert: lambda self, e: self.pgassert_sql(e),
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

            # Render EXCEPTION section if present
            ex = expression.args.get("exception")
            if ex is not None:
                parts.append(self.sql(ex))

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

        def pgexception_sql(self, expression: "PGException") -> str:
            parts: list[str] = ["EXCEPTION"]
            for when in expression.args.get("ifs") or []:
                parts.append(self.sql(when))
            return " ".join(parts)

        def pgwhen_sql(self, expression: "PGWhen") -> str:
            # Render condition expression with special handling for SQLSTATE tokens,
            # and support OR-composed conditions similar to CASE.
            def render_cond(node: exp.Expression) -> str:
                # Dedicated SQLSTATE expression
                if isinstance(node, PGSqlState):
                    return self.pgsqlstate_sql(node)
                # WHEN OTHERS
                if isinstance(node, PGOthers):
                    return self.pgothers_sql(node)
                # OR chain
                if isinstance(node, exp.Or):
                    return f"{render_cond(node.left)} OR {render_cond(node.right)}"
                return self.sql(node)

            condition = expression.args.get("condition")
            conds = render_cond(condition) if condition is not None else ""
            # Render body statements, each terminated by a semicolon
            body = expression.args.get("then") or []
            body_sql = " ".join(f"{self.sql(stmt)};" for stmt in body)
            return f"WHEN {conds} THEN {body_sql}"

        # Auto-discovered generator for PGOthers
        def pgothers_sql(self, expression: exp.Expression) -> str:
            return "OTHERS"

        # Auto-discovered generator for PGSqlState
        def pgsqlstate_sql(self, expression: exp.Expression) -> str:
            value = getattr(expression, "this", None)
            if value is not None:
                return f"SQLSTATE {self.sql(value)}"
            return "SQLSTATE"

        def pgreturn_sql(self, expression: PGReturn) -> str:
            # Prefer rendering RETURN QUERY if query flag is set
            if expression.args.get("query"):
                q = expression.args.get("this")
                return f"RETURN QUERY {self.sql(q)}"

            # Render RETURN NEXT when flagged
            if expression.args.get("next"):
                e = expression.args.get("this")
                return f"RETURN NEXT {self.sql(e)}"

            value = getattr(expression, "this", None)
            if value is not None:
                return f"RETURN {self.sql(value)}"
            return "RETURN"

        def pgraise_sql(self, expression: PGRaise) -> str:
            parts: list[str] = ["RAISE"]

            lvl = expression.args.get("level")
            if lvl is not None:
                # Render level in upper-case for canonical output
                parts.append(self.sql(lvl).upper())

            # payload: message (+args) | condition | sqlstate | none
            msg = expression.args.get("message")
            cond = expression.args.get("condition")
            state = expression.args.get("sqlstate")

            if msg is not None:
                seg = self.sql(msg)
                args = expression.args.get("expressions") or []
                if args:
                    seg = f"{seg}, " + ", ".join(self.sql(a) for a in args)
                parts.append(seg)
            elif cond is not None:
                parts.append(self.sql(cond))
            elif state is not None:
                # Call dedicated renderer to avoid relying on global transform
                parts.append(self.pgsqlstate_sql(state))

            using_args = expression.args.get("using") or []
            if using_args:
                parts.append("USING " + ", ".join(self.sql(a) for a in using_args))

            return " ".join(parts)

        def pgassert_sql(self, expression: PGAssert) -> str:
            cond = self.sql(expression.args.get("condition"))
            msg = expression.args.get("message")
            if msg is not None:
                return f"ASSERT {cond}, {self.sql(msg)}"
            return f"ASSERT {cond}"

        def pgloop_sql(self, expression: PGLoop) -> str:
            body_sql = " ".join(f"{self.sql(stmt)};" for stmt in expression.expressions)
            # Render exactly: LOOP <stmts>; END LOOP
            if body_sql:
                return f"LOOP {body_sql} END LOOP"
            return "LOOP END LOOP"

        def pgwhile_sql(self, expression: PGWhile) -> str:
            cond_sql = self.sql(expression.this)
            body_sql = " ".join(f"{self.sql(stmt)};" for stmt in expression.expressions)
            label = expression.args.get("label")
            suffix = f" {self.sql(label)}" if label is not None else ""
            if body_sql:
                return f"WHILE {cond_sql} LOOP {body_sql} END LOOP{suffix}"
            return f"WHILE {cond_sql} LOOP END LOOP{suffix}"

        def pgexit_sql(self, expression: PGExit) -> str:
            parts: list[str] = ["EXIT"]
            if expression.args.get("this") is not None:
                parts.append(self.sql(expression.this))
            if expression.args.get("when") is not None:
                parts.append("WHEN")
                parts.append(self.sql(expression.args.get("when")))
            return " ".join(parts)

        def pgcontinue_sql(self, expression: PGContinue) -> str:
            parts: list[str] = ["CONTINUE"]
            if expression.args.get("this") is not None:
                parts.append(self.sql(expression.this))
            if expression.args.get("when") is not None:
                parts.append("WHEN")
                parts.append(self.sql(expression.args.get("when")))
            return " ".join(parts)

        def pgopencursor_sql(self, expression: PGOpenCursor) -> str:
            # Unbound form: OPEN c [NO|SCROLL] FOR <query>
            if expression.args.get("expression") is not None:
                parts: list[str] = ["OPEN", self.sql(expression.this)]
                scroll = expression.args.get("scroll")
                if scroll is True:
                    parts.append("SCROLL")
                elif scroll is False:
                    parts.append("NO SCROLL")
                parts.append("FOR")
                parts.append(self.sql(expression.args.get("expression")))
                return " ".join(parts)

            # Bound form: OPEN c or OPEN c(<args>)
            name_sql = self.sql(expression.this)
            if getattr(expression, "expressions", None):
                args_sql = ", ".join(self.sql(arg) for arg in expression.expressions)
                name_sql = f"{name_sql}({args_sql})"
            return f"OPEN {name_sql}"

        # Auto-discovered generator for AssignArg
        def assignarg_sql(self, expression: AssignArg) -> str:
            return self.binary(expression, ":=")

        def pgfetch_sql(self, expression: PGFetch) -> str:
            targets_sql = ", ".join(self.sql(e) for e in expression.expressions)
            direction_expr = expression.args.get("direction")
            if direction_expr is not None:
                prep = expression.args.get("preposition") or "FROM"
                return f"FETCH {self.sql(direction_expr)} {prep} {self.sql(expression.this)} INTO {targets_sql}"
            return f"FETCH {self.sql(expression.this)} INTO {targets_sql}"

        def pgmove_sql(self, expression: "PGMove") -> str:
            direction_expr = expression.args.get("direction")
            if direction_expr is not None:
                prep = expression.args.get("preposition") or "FROM"
                return f"MOVE {self.sql(direction_expr)} {prep} {self.sql(expression.this)}"
            return f"MOVE {self.sql(expression.this)}"

        def pgclose_sql(self, expression: "PGClose") -> str:
            return f"CLOSE {self.sql(expression.this)}"

        # Direction generators (auto-discovered)
        def pgnext_sql(self, expression: PGNext) -> str:
            return "NEXT"

        def pgprior_sql(self, expression: PGPrior) -> str:
            return "PRIOR"

        def pgfirst_sql(self, expression: PGFirst) -> str:
            return "FIRST"

        def pglast_sql(self, expression: PGLast) -> str:
            return "LAST"

        def pgforward_sql(self, expression: PGForward) -> str:
            if expression.args.get("all"):
                return "FORWARD ALL"
            if expression.args.get("this") is not None:
                return f"FORWARD {self.sql(expression.this)}"
            return "FORWARD"

        def pgbackward_sql(self, expression: PGBackward) -> str:
            if expression.args.get("all"):
                return "BACKWARD ALL"
            if expression.args.get("this") is not None:
                return f"BACKWARD {self.sql(expression.this)}"
            return "BACKWARD"

        def pgabsolute_sql(self, expression: PGAbsolute) -> str:
            return f"ABSOLUTE {self.sql(expression.this)}"

        def pgrelative_sql(self, expression: PGRelative) -> str:
            return f"RELATIVE {self.sql(expression.this)}"

        def pgall_sql(self, expression: PGAll) -> str:
            return "ALL"


plpgsql = PlPgSQL
