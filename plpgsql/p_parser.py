from __future__ import annotations
import typing as t
from enum import IntEnum

from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import TokenType
from plpgsql.classes import *

from sqlglot import tokenizer_core

# Monkey patch sqlglot's tokenizer with PL/pgSQL keywords
tt = tokenizer_core.TokenType
PLPGSQL_CUSTOM_TOKEN_NAMES = (
    "ASSERT",
    "BY",
    "CLOSE",
    "CONTINUE",
    "DDOT",
    "EXIT",
    "FOREACH",
    "IF",
    "LOOP",
    "MOVE",
    "OPEN",
    "PERFORM",
    "RAISE",
    "RETURN",
    "REVERSE",
    "WHILE",
)
PLPGSQL_KEYWORD_TOKEN_NAMES = (
    *(token for token in PLPGSQL_CUSTOM_TOKEN_NAMES if token != "DDOT"),
    "DECLARE",
    "GET",
)
token_dict = {m.name: m.value for m in TokenType}

next_value = max(token_dict.values()) + 1
for token in PLPGSQL_CUSTOM_TOKEN_NAMES:
    token_dict[token] = next_value
    next_value += 1

TokenType = IntEnum('TokenType', token_dict)


class Parser(PostgresParser):
    STATEMENT_PARSERS = {
        **PostgresParser.STATEMENT_PARSERS,
        TokenType.BEGIN: lambda self: self._parse_plpgsql_block(),
        TokenType.DECLARE: lambda self: self._parse_plpgsql_block(),
        TokenType.UPDATE: lambda self: self._parse_pgupdate(),
        TokenType.DELETE: lambda self: self._parse_pgdelete(),
        TokenType.CASE: lambda self: self._parse_pgcase(),
        TokenType.RETURN: lambda self: self._parse_pgreturn(),
        TokenType.WHILE: lambda self: self._parse_pgwhile(),
        TokenType.IF: lambda self: self._parse_pgif(),
        TokenType.LOOP: lambda self: self._parse_pgloop(),
        TokenType.FOR: lambda self: self._parse_pgfor(),
        TokenType.FOREACH: lambda self: self._parse_pgforeach(),
        TokenType.EXIT: lambda self: self._parse_pgexit(),
        TokenType.CONTINUE: lambda self: self._parse_pgcontinue(),
        TokenType.RAISE: lambda self: self._parse_pgraise(),
        TokenType.ASSERT: lambda self: self._parse_pgassert(),
        TokenType.OPEN: lambda self: self._parse_pgopen(),
        TokenType.PERFORM: lambda self: self._parse_pgperform(),
        TokenType.FETCH: lambda self: self._parse_pgfetch(),
        TokenType.MOVE: lambda self: self._parse_pgmove(),
        TokenType.CLOSE: lambda self: self._parse_pgclose(),
        TokenType.EXECUTE: lambda self: self._parse_pgexecute(),
        TokenType.GET: lambda self: self._parse_pggetdiagnostics(),
    }

    # Intercept bare FOUND wherever an expression is allowed and parse it into PGFound
    NO_PAREN_FUNCTION_PARSERS = {
        **PostgresParser.NO_PAREN_FUNCTION_PARSERS,
        "FOUND": lambda self: self.expression(PGFound()),
    }

    def _match_expect(self, token_type: TokenType, *, advance: bool = True) -> None:
        if not self._match(token_type, advance=advance):
            self.raise_error(f"Expected token: {token_type.name}")

    def _match_text_expect(self, text: str, *, advance: bool = True) -> None:
        if not self._match_texts((text,), advance=advance):
            self.raise_error(f"Expected token: {text.upper()}")

    def _parse_pggetdiagnostics(self) -> PGGetDiagnostics:
        current = False
        stacked = False
        if self._match_texts(("CURRENT",)):
            current = True
        elif self._match_texts(("STACKED",)):
            stacked = True

        self._match_text_expect("DIAGNOSTICS")

        pairs: list[exp.Expression] = []

        def parse_item() -> exp.Expression:
            # Items are represented as identifier-like expressions
            ident = self._parse_id_var(any_token=True)
            if ident is None:
                self.raise_error("Expected diagnostics item after operator")
            return ident

        # 4. Parse first assignment pair (mandatory)
        var = self._parse_id_var(any_token=True)
        if var is None:
            self.raise_error("Expected variable after DIAGNOSTICS")

        pair = self._parse_named_pair(
            var,
            allowed_ops={TokenType.EQ, TokenType.COLON_EQ},
            rhs_parser=parse_item,
        )
        if pair is None:
            self.raise_error("Expected assignment operator (= or :=) after variable")
        pairs.append(pair)

        while self._match(TokenType.COMMA):
            var = self._parse_id_var(any_token=True)
            if var is None:
                self.raise_error("Expected variable after comma in GET DIAGNOSTICS")
            pair = self._parse_named_pair(
                var,
                allowed_ops={TokenType.EQ, TokenType.COLON_EQ},
                rhs_parser=parse_item,
            )
            if pair is None:
                self.raise_error("Expected assignment operator (= or :=) after variable")
            pairs.append(pair)

        return self.expression(PGGetDiagnostics(current=current, stacked=stacked, expressions=pairs))

    def _parse_named_pair(
        self,
        name_expr: exp.Expression,
        allowed_ops: set[TokenType],
        rhs_parser: t.Callable[[], exp.Expression] | None = None,
    ) -> exp.PropertyEQ | exp.EQ | exp.Kwarg | None:
        """Parse a named-argument style pair following a name expression.

        Supported operators are provided via ``allowed_ops`` and map to:
        - TokenType.COLON_EQ (:=)  -> exp.PropertyEQ
        - TokenType.EQ (=)         -> exp.EQ
        - TokenType.FARROW (=>)    -> exp.Kwarg

        If the next token is not an allowed operator, return None and do not
        consume anything. Otherwise, consume the operator, parse RHS via the
        provided ``rhs_parser`` (defaults to full expression), and return the
        appropriate expression node.
        """

        rhsp = rhs_parser or self._parse_expression

        # Map supported operators to their expression classes
        op_to_expr: dict[TokenType, type[exp.Expression]] = {
            TokenType.COLON_EQ: exp.PropertyEQ,
            TokenType.EQ: exp.EQ,
            TokenType.FARROW: exp.Kwarg,
        }

        # Filter to the allowed operators for this context
        candidates = tuple(t for t in op_to_expr.keys() if t in allowed_ops)
        if not candidates:
            return None

        # If the next token is not one of the allowed operators, do not consume
        if not self._match_set(candidates, advance=False):
            return None

        # Consume the operator and build the corresponding expression
        op = self._curr.token_type
        self._advance()
        klass = op_to_expr[op]
        return self.expression(klass(this=name_expr, expression=rhsp()))

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
        declare = None

        entry = self._prev.token_type if self._prev else None
        if entry == TokenType.BEGIN:
            pass
        elif entry == TokenType.DECLARE:
            declare = self._parse_pldeclare()
            self._match_expect(TokenType.BEGIN)
        else:
            self.raise_error("Expected BEGIN or DECLARE to start PL/pgSQL block")

        exception = None

        expressions = self._parse_statement_body(
            stop_texts=("EXCEPTION",),
            stop_tokens=(TokenType.END,),
            error_msg="Invalid expression / Unexpected token",
            strict=True,
            parse_one=self._parse_block_unit,
        )

        # If EXCEPTION section follows, parse it now (helper didn't consume it)
        if self._match_texts("EXCEPTION", advance=False):
            exception = self._parse_pgexception()

        # Require END to close the block
        self._match_expect(TokenType.END)

        return self.expression(
            PGBlock(expressions=expressions, declare=declare, exception=exception, begin=True)
        )

    def _parse_pg_assignment(self) -> exp.PropertyEQ | None:
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

        # Helper guarantees COLON_EQ -> PropertyEQ
        return pair  # type: ignore[return-value]

    def _parse_pgexception(self) -> exp.Expression:
        # Consume EXCEPTION keyword if not yet consumed
        self._match_text_expect("EXCEPTION")

        whens: list[exp.Expression] = []

        # Parse one or more WHEN clauses
        while self._match(TokenType.WHEN, advance=False):
            whens.append(self._parse_pgwhen())

        if not whens:
            self.raise_error("Invalid expression / Unexpected token")

        return self.expression(PGException(whens=whens))

    def _parse_pgwhen(self) -> exp.Expression:
        self._match_expect(TokenType.WHEN)

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

        self._match_expect(TokenType.THEN)

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
        if self._match_texts(("OTHERS",)):
            return self.expression(PGOthers())

        if self._match_texts(("SQLSTATE",)):
            # If a quoted literal follows, parse and attach it.
            if self._match(TokenType.STRING, advance=False):
                lit = self._parse_primary()
                if isinstance(lit, exp.Literal) and lit.is_string:
                    return self.expression(PGSqlState(this=lit))

            self.raise_error("SQLSTATE must be followed by a quoted literal")

        return self._parse_id_var()

    def _parse_pgif(self) -> PGIf:
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
        self._match_expect(TokenType.END)
        self._match_expect(TokenType.IF)

        return self.expression(PGIf(ifs=branches, default=default))

    def _parse_pgcase(self) -> PGCase:
        search_expr: exp.Expression | None = None
        if not self._match(TokenType.WHEN, advance=False):
            search_expr = self._parse_expression()

        branches: list[exp.Expression] = []
        while self._match(TokenType.WHEN, advance=False):
            branches.append(self._parse_pgcasewhen(search_expr))

        if not branches:
            self.raise_error("CASE requires at least one WHEN branch")

        default: list[exp.Expression] | None = None
        if self._match(TokenType.ELSE):
            default = self._parse_statement_body(
                stop_tokens=(TokenType.END,),
                error_msg="Invalid expression in CASE ELSE body / Unexpected token",
                strict=True,
                parse_one=self._parse_block_unit,
            )

        self._match_expect(TokenType.END)
        self._match_expect(TokenType.CASE)

        return self.expression(PGCase(this=search_expr, ifs=branches, default=default))

    def _parse_pgcasewhen(self, search_expr: exp.Expression | None) -> PGWhen:
        self._match_expect(TokenType.WHEN)

        if search_expr is None:
            condition = self._parse_expression()
            self._match_expect(TokenType.THEN)
        else:
            if self._match(TokenType.THEN, advance=False):
                self.raise_error("CASE search WHEN requires at least one expression before THEN")

            comparisons = [exp.EQ(this=search_expr.copy(), expression=self._parse_expression())]
            while self._match(TokenType.COMMA):
                comparisons.append(exp.EQ(this=search_expr.copy(), expression=self._parse_expression()))

            self._match_expect(TokenType.THEN)
            condition = comparisons[0] if len(comparisons) == 1 else exp.or_(*comparisons)

        then_body = self._parse_statement_body(
            stop_tokens=(TokenType.ELSE, TokenType.END),
            stop_texts=("WHEN",),
            error_msg="Invalid expression in CASE WHEN body / Unexpected token",
            strict=True,
            parse_one=self._parse_block_unit,
        )

        if not then_body:
            self.raise_error("CASE WHEN body requires at least one statement")

        return self.expression(PGWhen(condition=condition, then=then_body))

    def _parse_pgif_branch(self) -> PGIfBranch:
        # Parse <condition> THEN <statements>
        condition = self._parse_expression()
        self._match_expect(TokenType.THEN)

        then_body = self._parse_pgif_body()
        if not then_body:
            self.raise_error("IF branch requires at least one statement")

        return self.expression(PGIfBranch(condition=condition, then=then_body))

    def _parse_pgif_body(self) -> list[exp.Expression]:
        return self._parse_statement_body(
            stop_texts=("ELSIF", "ELSEIF"),
            stop_tokens=(TokenType.ELSE, TokenType.END),
            error_msg="Invalid expression in IF body / Unexpected token",
            strict=True,
            parse_one=self._parse_block_unit,
        )

    def _parse_block_unit(self) -> exp.Expression | None:
        assignment = self._parse_pg_assignment()
        if assignment is not None:
            return assignment
        return self._parse_statement()

    def _parse_pldeclare(self) -> exp.Declare:
        items: list[exp.Expression] = self._parse_statement_body(
            stop_texts=("BEGIN",),
            stop_tokens=(),
            error_msg="Invalid DECLARE item / Unexpected token",
            strict=True,
            parse_one=self._parse_pldeclareitem,
        )

        return self.expression(exp.Declare(expressions=items))

    def _parse_pldeclareitem(self) -> PGDeclareItem | None:
        ident = self._parse_id_var()
        if not ident:
            return None

        # Optional CONSTANT modifier
        is_constant = self._match_texts(("CONSTANT",))

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

        # Detect cursor declaration before type parsing:
        index = self._index
        scroll: bool | None = None
        if self._match_texts(("NO",)):
            if self._match_texts(("SCROLL",)):
                scroll = False
            else:
                # Not a valid cursor prelude, rollback
                self._retreat(index)
        elif self._match_texts(("SCROLL",)):
            scroll = True

        # If SCROLL/NO SCROLL matched, require CURSOR next; else try bare CURSOR
        if scroll is not None:
            if self._match_texts(("CURSOR",)):
                return self._parse_pl_declare_cursor(ident, is_constant, scroll)
            # Roll back if not actually a cursor declaration
            self._retreat(index)
        elif self._match_texts(("CURSOR",)):
            return self._parse_pl_declare_cursor(ident, is_constant, None)

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

    def _parse_pl_declare_cursor(
        self, ident: exp.Expression, is_constant: bool, scroll: bool | None
    ) -> PGDeclareItem:
        # Optional argument declaration list: ( name type [, ...] )
        cursor_args: list[exp.Expression] | None = None
        if self._match(TokenType.L_PAREN):
            cursor_args = self._parse_csv(self._parse_pl_cursor_arg)
            self._match_expect(TokenType.R_PAREN)

        # Required FOR <query>
        self._match_expect(TokenType.FOR)

        query = self._parse_statement()
        if query is None:
            self.raise_error("Expected query after CURSOR ... FOR")

        return self.expression(
            PGDeclareItem(
                this=ident,
                cursor=True,
                scroll=scroll,
                cursor_args=cursor_args,
                query=query,
                constant=is_constant,
            )
        )

    def _parse_pl_cursor_arg(self) -> PGCursorArg:
        name = self._parse_id_var()
        arg_type = self._parse_type() or self._parse_types()
        return self.expression(PGCursorArg(this=name, kind=arg_type))

    def _parse_statement(self) -> exp.Expr | None:
        return super()._parse_statement()

    def _parse_pginsert(self) -> exp.Expression:
        return super()._parse_insert()

    def _parse_returning(self) -> exp.Returning | None:
        # Override base to support INTO [STRICT] <target>[, ...]
        if not self._match(TokenType.RETURNING):
            return None

        expressions = self._parse_csv(self._parse_expression)

        into = None
        if self._match(TokenType.INTO):
            strict = self._match_texts(("STRICT",))
            # Parse one or more identifier-like targets (variables)
            targets = self._parse_csv(lambda: self._parse_id_var(any_token=True))
            if not targets:
                self.raise_error("Expected target list after INTO")

            into = self.expression(
                PGInto(
                    this=targets[0],
                    expressions=targets if len(targets) > 1 else None,
                    strict=strict,
                )
            )

        return self.expression(PGReturning(expressions=expressions, into=into))

    def _parse_into(self) -> exp.Into | None:
        if not self._match(TokenType.INTO):
            return None

        strict = self._match_texts(("STRICT",))
        temp = self._match(TokenType.TEMPORARY)
        unlogged = self._match_text_seq("UNLOGGED")
        self._match(TokenType.TABLE)

        targets = self._parse_csv(lambda: self._parse_table(schema=True))
        if not targets:
            self.raise_error("Expected target list after INTO")

        return self.expression(
            PGInto(
                this=targets[0],
                expressions=targets if len(targets) > 1 else None,
                temporary=temp,
                unlogged=unlogged,
                strict=strict,
            )
        )

    def _extract_trailing_where_current_of(self) -> tuple[int, exp.Identifier] | None:
        statement_index = self._index
        where_index = -1

        for index in range(statement_index, self._tokens_size - 3):
            token = self._tokens[index]
            if token.text.upper() != "WHERE":
                continue

            if (
                self._tokens[index + 1].text.upper() == "CURRENT"
                and self._tokens[index + 2].text.upper() == "OF"
            ):
                where_index = index

        if where_index < 0:
            return None

        cursor_token = self._tokens[where_index + 3]
        if cursor_token.token_type not in {TokenType.IDENTIFIER, TokenType.VAR, TokenType.STRING}:
            self.raise_error("Expected cursor name after WHERE CURRENT OF", token=cursor_token)

        cursor = exp.to_identifier(
            cursor_token.text,
            quoted=cursor_token.token_type in {TokenType.IDENTIFIER, TokenType.STRING},
        )
        cursor.update_positions(cursor_token)

        for trailing_token in self._tokens[where_index + 4 : self._tokens_size]:
            if trailing_token.token_type not in {TokenType.SEMICOLON, TokenType.SENTINEL}:
                self.raise_error("Invalid expression after WHERE CURRENT OF", token=trailing_token)

        return where_index, cursor

    def _parse_pg_dml_with_current_of(self, parse: t.Callable[[], exp.Expression]) -> tuple[exp.Expression, exp.Identifier | None]:
        current_of_info = self._extract_trailing_where_current_of()
        original_tokens_size = self._tokens_size

        if current_of_info:
            self._tokens_size = current_of_info[0]

        statement = parse()
        self._tokens_size = original_tokens_size

        if current_of_info:
            self._retreat(original_tokens_size)

        return statement, current_of_info and current_of_info[1]

    def _parse_pgupdate(self) -> PGUpdate:
        update, current_of = self._parse_pg_dml_with_current_of(super()._parse_update)
        return self.expression(PGUpdate(**update.args, current_of=current_of))

    def _parse_pgdelete(self) -> PGDelete:
        delete, current_of = self._parse_pg_dml_with_current_of(super()._parse_delete)
        return self.expression(PGDelete(**delete.args, current_of=current_of))

    def _parse_pgwhile(self) -> exp.WhileBlock:
        # Parse condition expression
        cond = self._parse_expression()

        # Guard against accidental aliasing like: <cond> AS LOOP
        if isinstance(cond, exp.Alias):
            alias = cond.args.get("alias")
            if isinstance(alias, exp.Identifier) and alias.name.upper() == "LOOP":
                cond = cond.this
            else:
                self._match_expect(TokenType.LOOP)
        else:
            self._match_expect(TokenType.LOOP)

        # Parse body statements until END (lax mode to preserve original behavior)
        body: list[exp.Expression] = self._parse_statement_body(
            stop_tokens=(TokenType.END,),
            strict=False,
        )
        self._match_expect(TokenType.END)
        self._match_expect(TokenType.LOOP)

        # Optional label
        label = self._parse_id_var(any_token=True)
        self._match(TokenType.SEMICOLON)

        return self.expression(exp.WhileBlock(this=cond, body=body, label=label))

    def _parse_pgperform(self) -> PGPerform:
        if self._match(TokenType.SENTINEL, advance=False):
            self.raise_error("Expected query body after PERFORM")

        perform_index = self._index - 1
        perform_token = self._tokens[perform_index]
        original_type = perform_token.token_type

        perform_token.token_type = TokenType.SELECT
        try:
            self._retreat(perform_index)
            query = self._parse_select()
        finally:
            perform_token.token_type = original_type

        if not isinstance(query, exp.Select):
            self.raise_error("Expected query body after PERFORM")

        return self.expression(PGPerform(**query.args))

    def _parse_pgfor(self) -> PGForIn:
        # Parse loop target identifier/variable
        target = self._parse_id_var()

        self._match_expect(TokenType.IN)
        reverse = self._match(TokenType.REVERSE)

        # Try range form: <start> .. <end> [BY <step>] LOOP
        start_index = self._index
        start_expr = self._parse_bitwise()
        if start_expr is not None and self._match(TokenType.DDOT):
            end_expr = self._parse_bitwise()
            step_expr = self._parse_bitwise() if self._match(TokenType.BY) else None
            self._match_expect(TokenType.LOOP)
            body = self._parse_loop_body()
            return self.expression(
                PGForIn(
                    this=target,
                    reverse=reverse or None,
                    start=start_expr,
                    end=end_expr,
                    step=step_expr,
                    expressions=body,
                    label=self._parse_loop_label(),
                )
            )

        if reverse:
            self.raise_error("Expected '..' range after REVERSE in FOR header")

        # Not a range: rewind and parse the query/cursor form
        self._retreat(start_index)
        return self._parse_pgfor_query(target)

    def _parse_pgfor_query(self, target: exp.Expression) -> PGForIn:
        # If the header begins with EXECUTE, parse via _parse_pgexecute and
        # explicitly reject INTO / INTO STRICT in this context, mirroring
        # RETURN QUERY EXECUTE semantics.
        if self._match(TokenType.EXECUTE):
            query = self._parse_pgexecute()
            if query.args.get("expressions") or query.args.get("strict"):
                self.raise_error("INTO is not allowed in FOR IN EXECUTE")
        else:
            start_index = self._index
            query = None

            cursor = self._parse_id_var()
            if cursor is not None:
                args = None
                if self._match(TokenType.L_PAREN, advance=False):
                    args = self._parse_cursor_call_args()

                # Cursor call only if the header ends here (next token is LOOP)
                if self._match(TokenType.LOOP, advance=False):
                    query = self.expression(PGCursorCall(this=cursor, expressions=args))

            if query is None:
                self._retreat(start_index)
                query = self._parse_statement()

        self._match_expect(TokenType.LOOP)
        body = self._parse_loop_body()
        return self.expression(
            PGForIn(
                this=target,
                query=query,
                expressions=body,
                label=self._parse_loop_label(),
            )
        )

    def _parse_pgforeach(self) -> PGForEach:
        # Loop target variable
        target = self._parse_id_var()

        slice_expr = None
        if self._match_texts(("SLICE",)):
            slice_expr = self._parse_number()
            if slice_expr is None:
                self.raise_error("Expected a number after SLICE")

        self._match_expect(TokenType.IN)
        self._match_expect(TokenType.ARRAY)

        # The array expression stops at the LOOP token naturally.
        array_expr = self._parse_bitwise()
        self._match_expect(TokenType.LOOP)
        body = self._parse_loop_body()
        return self.expression(
            PGForEach(
                this=target,
                slice=slice_expr,
                expression=array_expr,
                expressions=body,
                label=self._parse_loop_label(),
            )
        )

    def _parse_loop_body(self) -> list[exp.Expression]:
        body = self._parse_statement_body(stop_tokens=(TokenType.END,), strict=False)
        self._match_expect(TokenType.END)
        self._match_expect(TokenType.LOOP)
        return body or []

    def _parse_loop_label(self) -> exp.Expression | None:
        label = self._parse_id_var(any_token=True)
        self._match(TokenType.SEMICOLON)
        return label

    def _parse_pgassert(self) -> PGAssert:
        condition = self._parse_expression()

        message = None
        if self._match(TokenType.COMMA):
            message = self._parse_expression()

        return self.expression(PGAssert(condition=condition, message=message))

    def _parse_pgraise(self) -> PGRaise:
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

        # Helper to parse USING options into PropertyEQ/EQ entries
        def _parse_using_list() -> list[exp.Expression]:
            # Current token should be USING (not yet consumed)
            self._match_expect(TokenType.USING)
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
        # Support RETURN QUERY <query>; and RETURN QUERY EXECUTE ... [USING ...];
        if self._match_texts("QUERY"):
            # Fast-path for dynamic EXECUTE variant
            if self._match(TokenType.EXECUTE):
                exec_node = self._parse_pgexecute()

                # Prohibit INTO / INTO STRICT in RETURN QUERY EXECUTE form
                if exec_node.args.get("expressions") or exec_node.args.get("strict"):
                    self.raise_error("INTO is not allowed in RETURN QUERY EXECUTE")

                return self.expression(PGReturn(this=exec_node, query=True))

            # Otherwise parse a full query-producing statement (SELECT/WITH/VALUES/INSERT ... RETURNING)
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
        # Parse body statements until END using the shared helper
        body: list[exp.Expression] = self._parse_statement_body(
            stop_tokens=(TokenType.END,),
            error_msg="Invalid expression inside LOOP / Unexpected token",
            strict=True,
        )

        # Consume END and then require trailing LOOP
        self._match_expect(TokenType.END)
        self._match_expect(TokenType.LOOP)

        return self.expression(PGLoop(body=body))

    def _parse_pgexit_or_continue(self, *, token_type: TokenType, expr_cls: type[exp.Expression]):
        """Parse EXIT/CONTINUE constructs which share the same grammar.

        Syntax: <KEYWORD> [label] [WHEN <expr>]
        """
        label = None
        condition = None

        # Optional label unless the next token starts a WHEN clause
        if self._curr is not None and self._curr.text.upper() != "WHEN":
            label = self._parse_id_var()

        # Optional WHEN <expression>
        if self._match(TokenType.WHEN):
            condition = self._parse_expression()

        # Build node. For EXIT, use the PL/pgSQL subclass (PGExit) which extends
        # the shared exp.Leave with an optional WHEN clause.
        return self.expression(expr_cls(this=label, when=condition))

    def _parse_pgexit(self) -> PGExit:
        return self._parse_pgexit_or_continue(token_type=TokenType.EXIT, expr_cls=PGExit)

    def _parse_pgcontinue(self) -> PGContinue:
        return self._parse_pgexit_or_continue(token_type=TokenType.CONTINUE, expr_cls=PGContinue)

    def _parse_cursor_call_args(self) -> list[exp.Expression]:
        """Parse a parenthesized cursor argument list and consume the closing ')'."""
        self._advance()

        args: list[exp.Expression] = []
        if not self._match(TokenType.R_PAREN, advance=False):
            while True:
                first = self._parse_expression()
                pair = self._parse_named_pair(
                    first,
                    allowed_ops={TokenType.COLON_EQ, TokenType.FARROW},
                    rhs_parser=self._parse_expression,
                )
                args.append(pair or first)

                if not self._match(TokenType.COMMA):
                    break
                if self._match(TokenType.R_PAREN, advance=False):
                    self.raise_error("Trailing comma is not allowed in cursor argument list")

        self._match_expect(TokenType.R_PAREN)

        return args

    def _parse_open_args(self) -> list[exp.Expression]:
        """Parse an OPEN cursor argument list and return the collected args.

        Supports positional arguments, name := value (PropertyEQ), and
        name => value (Kwarg).

        Precondition: current token is '(' (not yet consumed).
        Postcondition: the closing ')' is consumed.
        """
        return self._parse_cursor_call_args()

    def _parse_pgopen(self) -> PGOpenCursor:
        # Cursor variable identifier
        cursor = self._parse_id_var()

        # Bound cursor with arguments: OPEN c(<args>) where args can be positional,
        # name := value (PropertyEQ), or name => value (Kwarg)
        if self._match(TokenType.L_PAREN, advance=False):
            args = self._parse_open_args()
            return self.expression(PGOpenCursor(this=cursor, expressions=args))

        # Optional [[NO] SCROLL]
        scroll: bool | None = None
        if self._match_texts("NO"):
            self._match_text_expect("SCROLL")
            scroll = False
        elif self._match_texts("SCROLL"):
            scroll = True

        # If there's no FOR and no SCROLL/NO SCROLL, treat as bound cursor with zero args: OPEN c;
        if not self._match(TokenType.FOR):
            if scroll is None:
                return self.expression(PGOpenCursor(this=cursor))
            # If SCROLL/NO SCROLL was provided, FOR is required
            self._match_expect(TokenType.FOR)

        if self._match(TokenType.EXECUTE):
            query = self._parse_pgexecute()
            if query.args["expressions"]:
                self.raise_error("INTO is not allowed in OPEN FOR EXECUTE")
        else:
            query = self._parse_statement()
            if query is None:
                self.raise_error("Expected query after OPEN ... FOR")

        return self.expression(PGOpenCursor(this=cursor, expression=query, scroll=scroll))

    def _parse_pgfetch(self) -> PGFetch:
        # Parse optional direction, optional preposition (required when direction given), and cursor
        direction, preposition, cursor = self._parse_pg_direction_and_cursor(after_kw="FETCH")

        # INTO keyword
        self._match_expect(TokenType.INTO)

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
        cursor = self._parse_id_var()
        return self.expression(PGClose(this=cursor))

    def _parse_pgexecute(self) -> PGExecute:
        # Command-string: any scalar expression (literal, '||' concat, function call).
        # _parse_expression naturally stops at INTO / USING (non-alias tokens).
        command = self._parse_expression()
        if command is None:
            self.raise_error("Expected command string after EXECUTE")

        targets: list[exp.Expression] | None = None
        strict = False
        using: list[exp.Expression] | None = None

        # Optional INTO [STRICT] target [, ...]
        if self._match(TokenType.INTO):
            # STRICT is tokenized as VAR, so match by text
            strict = self._match_texts(("STRICT",))

            # One or more targets separated by commas
            targets = self._parse_csv(self._parse_expression)
            if not targets:
                self.raise_error("Expected target list after INTO in EXECUTE")

        # Optional USING expression [, ...]
        if self._match(TokenType.USING):
            # Require at least one expression and disallow trailing commas
            first = self._parse_expression()
            if first is None:
                self.raise_error("Expected expression list after USING in EXECUTE")
            using = [first]
            while self._match(TokenType.COMMA):
                nxt = self._parse_expression()
                if nxt is None:
                    self.raise_error("Expected expression after comma in USING list")
                using.append(nxt)

        return self.expression(
            PGExecute(
                this=command,
                expressions=targets,
                strict=strict,
                using=using or [],
            )
        )

    def _parse_pg_direction_and_cursor(
        self, *, after_kw: str
    ) -> tuple[exp.Expression | None, str | None, exp.Expression]:
        """
        Parse optional direction and required preposition (if direction present), then cursor name.
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

        # Handle FORWARD/BACKWARD with optional count/ALL
        if self._match_texts(("FORWARD", "BACKWARD")):
            which = (self._prev.text or "").upper()
            cls = PGForward if which == "FORWARD" else PGBackward
            # Optional ALL or count after FORWARD/BACKWARD
            if self._match_texts("ALL"):
                direction = self.expression(cls(all=True))
            else:
                # A number
                if self._match_set((TokenType.NUMBER, TokenType.DASH), advance=False):
                    count_expr = self._parse_bitwise()
                    direction = self.expression(cls(this=count_expr))
                else:
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
            elif self._match_set((TokenType.NUMBER, TokenType.DASH), advance=False):
                count_expr = self._parse_bitwise()
                direction = count_expr
                preposition = _parse_required_preposition(
                    f"Expected FROM or IN after {after_kw} count"
                )
            else:
                if self._match_texts(("FROM", "IN")):
                    preposition = (self._prev.text or "").upper()

        cursor = self._parse_id_var()
        return direction, preposition, cursor
