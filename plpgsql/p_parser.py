from __future__ import annotations
import typing as t

from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import TokenType
from plpgsql.classes import *



class Parser(PostgresParser):
    STATEMENT_PARSERS = {
        **PostgresParser.STATEMENT_PARSERS,
        TokenType.BEGIN: lambda self: self._parse_plpgsql_block(),
        TokenType.DECLARE: lambda self: self._parse_plpgsql_block(),
    }

    # Map leading PL/pgSQL statement keywords (by lexeme) to parser callables.
    # These arrive as identifier/VAR tokens, so we dispatch by text.upper().
    PLPGSQL_STATEMENT_PARSERS = {
        "RETURN": lambda self: self._parse_pgreturn(),
        "WHILE": lambda self: self._parse_pgwhile(),
        "IF": lambda self: self._parse_pgif(),
        "LOOP": lambda self: self._parse_pgloop(),
        "EXIT": lambda self: self._parse_pgexit(),
        "CONTINUE": lambda self: self._parse_pgcontinue(),
        "RAISE": lambda self: self._parse_pgraise(),
        "ASSERT": lambda self: self._parse_pgassert(),
        "OPEN": lambda self: self._parse_pgopen(),
        "FETCH": lambda self: self._parse_pgfetch(),
        "MOVE": lambda self: self._parse_pgmove(),
        "CLOSE": lambda self: self._parse_pgclose(),
    }

    def _parse_named_pair(
        self,
        name_expr: exp.Expression,
        allowed_ops: set[TokenType],
        rhs_parser: t.Callable[[], exp.Expression] | None = None,
    ) -> exp.Expression | None:
        """Parse a named-argument style pair following a name expression.

        Supported operators are provided via ``allowed_ops`` and map to:
        - TokenType.COLON_EQ (:=)  -> AssignArg
        - TokenType.EQ (=)         -> exp.EQ
        - TokenType.FARROW (=>)    -> exp.Kwarg

        If the next token is not an allowed operator, return None and do not
        consume anything. Otherwise, consume the operator, parse RHS via the
        provided ``rhs_parser`` (defaults to full expression), and return the
        appropriate expression node.
        """

        rhsp = rhs_parser or self._parse_expression

        if self._match(TokenType.COLON_EQ, advance=False) and TokenType.COLON_EQ in allowed_ops:
            self._advance()
            return self.expression(AssignArg(this=name_expr, expression=rhsp()))

        if self._match(TokenType.EQ, advance=False) and TokenType.EQ in allowed_ops:
            self._advance()
            return self.expression(exp.EQ(this=name_expr, expression=rhsp()))

        if self._match(TokenType.FARROW, advance=False) and TokenType.FARROW in allowed_ops:
            self._advance()
            return self.expression(exp.Kwarg(this=name_expr, expression=rhsp()))

        return None

    def _parse_statement_body(
        self,
        *,
        stop_texts: tuple[str, ...] = (),
        stop_tokens: tuple[TokenType, ...] = (),
        error_msg: str = "Invalid expression / Unexpected token",
        strict: bool = True,
        parse_one: t.Callable[[], exp.Expression | None] | None = None,
    ) -> list[exp.Expression]:
        """Parse a sequence of ';'-delimited statements until a terminator.

        This advances through chunk-delimited statements, collecting one parsed
        unit per chunk via ``parse_one`` (defaults to ``self._parse_statement``).

        Terminators are only peeked (not consumed) so callers can decide how to
        handle them (e.g., ``END``, ``WHEN``, ``EXCEPTION``, ``BEGIN``).

        When ``strict`` is True, the helper enforces that each parsed unit
        fully consumes its chunk, raises ``error_msg`` if unconsumed tokens
        remain, calls ``check_errors()``, and then advances to the next chunk.
        When ``strict`` is False, it simply advances to the next chunk after
        each parsed unit without extra checks (matching existing laxer callers).
        """

        out: list[exp.Expression] = []
        parse = parse_one or self._parse_statement

        # Normalize stop_texts to uppercase for lexeme comparison
        stop_texts_upper = tuple(s.upper() for s in stop_texts)

        while True:
            # If we've consumed the current chunk, move to the next one
            if self._index >= self._tokens_size:
                self._advance_chunk()

            # No more tokens in this chunked stream
            if not self._curr:
                break

            # Stop if a token-type terminator is next (but don't consume)
            if stop_tokens and self._match_set(stop_tokens, advance=False):
                break

            # Stop if a lexeme (identifier-like) terminator is next
            if stop_texts_upper and self._curr.text.upper() in stop_texts_upper:
                break

            # Parse one unit from this chunk
            node = parse()
            if node is not None:
                out.append(node)

            if strict:
                # After parsing a unit, there should be no leftover tokens in the chunk
                if self._index < self._tokens_size:
                    self.raise_error(error_msg)
                # Surface any accumulated errors (base Parser pattern)
                self.check_errors()

            # Proceed to the next chunk regardless of strictness
            self._advance_chunk()

        return out

    def _parse_plpgsql_block(self) -> PGBlock:
        # Determine entry: dispatcher consumed the first keyword into _prev
        declare = None
        if self._prev and self._prev.token_type == TokenType.DECLARE:
            # Started with DECLARE: parse declaration section, then require BEGIN
            declare = self._parse_pldeclare()
            if not self._match(TokenType.BEGIN):
                self.raise_error("Expected BEGIN after DECLARE or at block start")

        exception = None

        # Parse statements (including assignments) until EXCEPTION or END
        def _parse_block_unit() -> exp.Expression | None:
            assignment = self._parse_pg_assignment()
            if assignment is not None:
                return assignment
            return self._parse_statement()

        expressions = self._parse_statement_body(
            stop_texts=("EXCEPTION",),
            stop_tokens=(TokenType.END,),
            error_msg="Invalid expression / Unexpected token",
            strict=True,
            parse_one=_parse_block_unit,
        )

        # If EXCEPTION section follows, parse it now (helper didn't consume it)
        if self._match_texts("EXCEPTION", advance=False):
            exception = self._parse_pgexception()

        # Require END to close the block
        if not self._match(TokenType.END):
            self.raise_error("Expected END to close block")

        return self.expression(
            PGBlock(expressions=expressions, declare=declare, exception=exception, begin=True)
        )

    def _parse_pg_assignment(self) -> AssignArg | None:
        """Parse a simple PL/pgSQL assignment statement inside a block.

        Pattern: <identifier> := <expression>

        Notes:
        - We do NOT accept '=' as assignment. If we detect '<ident> =', raise a ParseError.
        - Parsing is local to the current chunk (terminated by ';').
        - On non-match, parser state is restored and None is returned.
        """

        # Use index-based backtracking instead of manual state juggling
        index = self._index

        # LHS must be an identifier-like variable
        lhs = self._parse_id_var()
        if not lhs:
            self._retreat(index)
            return None

        # Preserve specific error for accidental '=' usage
        if self._match(TokenType.EQ, advance=False):
            self.raise_error("Use := for assignment in PL/pgSQL blocks")
            return None  # unreachable, keeps type-checkers happy

        # Delegate operator + RHS parsing to shared helper (only ':=')
        pair = self._parse_named_pair(
            lhs,
            allowed_ops={TokenType.COLON_EQ},
            rhs_parser=self._parse_expression,
        )

        if pair is None:
            self._retreat(index)
            return None

        # Helper guarantees COLON_EQ -> AssignArg
        return pair  # type: ignore[return-value]

    def _parse_pgexception(self) -> exp.Expression:
        # Consume EXCEPTION keyword if not yet consumed
        if not self._match_texts("EXCEPTION"):
            self.raise_error("Expected EXCEPTION in block")

        whens: list[exp.Expression] = []

        # Parse one or more WHEN clauses
        while self._match(TokenType.WHEN, advance=False):
            whens.append(self._parse_pgwhen())

        if not whens:
            self.raise_error("Invalid expression / Unexpected token")

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
        thens: list[exp.Expression] = self._parse_statement_body(
            stop_texts=("WHEN",),
            stop_tokens=(TokenType.END,),
            error_msg="Invalid expression in WHEN body / Unexpected token",
            strict=True,
        )

        if not thens:
            self.raise_error("WHEN body requires at least one statement")

        # Combine multiple conditions into a single OR expression like exp.Case does
        condition_expr = conditions[0]
        if len(conditions) > 1:
            # Use builder to combine with OR respecting nesting
            condition_expr = exp.or_(*conditions)

        return self.expression(PGWhen(condition=condition_expr, then=thens))

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

    def _parse_pgif(self) -> PGIf:
        # Consume IF keyword
        if not self._match_texts("IF"):
            self.raise_error("Expected IF")

        # First branch starts immediately after IF
        branches: list[exp.Expression] = [self._parse_pgif_branch()]

        # Zero or more ELSIF / ELSEIF branches
        while self._match_texts(("ELSIF", "ELSEIF")):
            branches.append(self._parse_pgif_branch())

        # Optional ELSE branch
        default: list[exp.Expression] | None = None
        if self._match(TokenType.ELSE):
            default = self._parse_pgif_body()

        # Require END IF to close
        if not self._match(TokenType.END):
            self.raise_error("Expected END to close IF block")
        if not self._match_texts("IF"):
            self.raise_error("Expected IF after END in IF block")

        return self.expression(PGIf(ifs=branches, default=default))

    def _parse_pgif_branch(self) -> PGIfBranch:
        # Parse <condition> THEN <statements>
        condition = self._parse_expression()
        if not self._match(TokenType.THEN):
            self.raise_error("Expected THEN in IF branch")

        then_body = self._parse_pgif_body()
        if not then_body:
            self.raise_error("IF branch requires at least one statement")

        return self.expression(PGIfBranch(condition=condition, then=then_body))

    def _parse_pgif_body(self) -> list[exp.Expression]:
        # Reuse assignment-aware unit parser from block bodies
        def _unit() -> exp.Expression | None:
            assignment = self._parse_pg_assignment()
            if assignment is not None:
                return assignment
            return self._parse_statement()

        return self._parse_statement_body(
            stop_texts=("ELSIF", "ELSEIF"),
            stop_tokens=(TokenType.ELSE, TokenType.END),
            error_msg="Invalid expression in IF body / Unexpected token",
            strict=True,
            parse_one=_unit,
        )

    def _parse_pldeclare(self) -> PGDeclare:
        items: list[exp.Expression] = self._parse_statement_body(
            stop_texts=("BEGIN",),
            stop_tokens=(),
            error_msg="Invalid DECLARE item / Unexpected token",
            strict=True,
            parse_one=self._parse_pldeclareitem,
        )

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
        if self._curr:
            parser = self.PLPGSQL_STATEMENT_PARSERS.get(self._curr.text.upper())
            if parser:
                return parser(self)
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

        # Parse body statements until END (lax mode to preserve original behavior)
        body: list[exp.Expression] = self._parse_statement_body(
            stop_tokens=(TokenType.END,),
            strict=False,
        )

        # Consume END then require LOOP
        if not self._match(TokenType.END):
            self.raise_error("Expected END to close WHILE block")
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

        # Helper to parse USING options into AssignArg/EQ entries
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

                pair = self._parse_named_pair(
                    name,
                    allowed_ops={TokenType.COLON_EQ, TokenType.EQ},
                    rhs_parser=self._parse_expression,
                )
                if pair is None:
                    self.raise_error("Expected ':=' or '=' in USING option")
                opts.append(pair)

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

        # Parse body statements until END using the shared helper
        body: list[exp.Expression] = self._parse_statement_body(
            stop_tokens=(TokenType.END,),
            error_msg="Invalid expression inside LOOP / Unexpected token",
            strict=True,
        )

        # Consume END and then require trailing LOOP
        if not self._match(TokenType.END):
            self.raise_error("Expected END to close LOOP block")
        if not self._match_texts("LOOP"):
            self.raise_error("Expected LOOP after END in LOOP block")

        return self.expression(PGLoop(expressions=body))

    def _parse_pgexit_or_continue(self, *, keyword: str, expr_cls: type[exp.Expression]):
        """Parse EXIT/CONTINUE constructs which share the same grammar.

        Syntax: <KEYWORD> [label] [WHEN <expr>]
        """
        if not self._match_texts(keyword):
            self.raise_error(f"Expected {keyword}")

        label = None
        condition = None

        # Optional label unless the next token starts a WHEN clause
        if self._curr is not None and self._curr.text.upper() != "WHEN":
            label = self._parse_id_var()

        # Optional WHEN <expression>
        if self._match(TokenType.WHEN):
            condition = self._parse_expression()

        return self.expression(expr_cls(this=label, when=condition))

    def _parse_pgexit(self) -> PGExit:
        return self._parse_pgexit_or_continue(keyword="EXIT", expr_cls=PGExit)

    def _parse_pgcontinue(self) -> PGContinue:
        return self._parse_pgexit_or_continue(keyword="CONTINUE", expr_cls=PGContinue)

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

                pair = self._parse_named_pair(
                    first,
                    allowed_ops={TokenType.COLON_EQ, TokenType.FARROW},
                    rhs_parser=self._parse_expression,
                )
                if pair is not None:
                    args.append(pair)
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
            cls = PGForward if which == "FORWARD" else PGBackward
            # Optional ALL or count after FORWARD/BACKWARD
            if self._match_texts("ALL"):
                direction = self.expression(cls(all=True))
            else:
                # Parse numeric count only when the next token(s) are numeric
                if _next_is_numeric():
                    count_expr = self._parse_bitwise()
                    direction = self.expression(cls(this=count_expr))
                else:
                    # No count provided; just the keyword
                    direction = self.expression(cls())

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
