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
    # Optionally includes an exception section captured as `exception`.
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
    """A single WHEN ... THEN ... entry inside an EXCEPTION section.

    Mirror exp.When by using `condition` for the predicate and `true` for the body.
    """

    arg_types = {"condition": True, "then": True}


class PGOthers(exp.Expression):
    """Represents the OTHERS keyword in EXCEPTION WHEN OTHERS THEN ..."""

    arg_types: dict[str, bool] = {}


class PGLoop(exp.Expression):
    """A PL/pgSQL LOOP ... END LOOP construct.

    Stores inner statements in ``expressions`` similar to :class:`PGBlock`.
    """

    arg_types = {"expressions": True}


class PGExit(exp.Expression):
    """A PL/pgSQL EXIT statement.

    Syntax:
      EXIT [ label ] [ WHEN <expression> ];

    - Optional label is stored in ``this`` (as an identifier expression).
    - Optional condition after WHEN is stored under ``when``.
    """

    arg_types = {"this": False, "when": False}


class PGContinue(exp.Expression):
    """A PL/pgSQL CONTINUE statement.

    Syntax:
      CONTINUE [ label ] [ WHEN <expression> ];

    - Optional label is stored in ``this`` (as an identifier expression).
    - Optional condition after WHEN is stored under ``when``.
    """

    arg_types = {"this": False, "when": False}


class PGOpenCursor(exp.Expression):
    """A PL/pgSQL OPEN cursor statement.

    Supports two forms:
      - Unbound: OPEN cursorvar [ [ NO ] SCROLL ] FOR query;
      - Bound:   OPEN cursorvar [ ( arg_value [, ...] ) ];

    - Cursor variable name is stored in ``this``.
    - For unbound form: the query after FOR is stored in ``expression`` and optional
      scroll behavior is stored in ``scroll`` (True => SCROLL, False => NO SCROLL).
    - For bound form: positional argument values are stored in ``expressions``.
    """

    arg_types = {"this": True, "expression": False, "scroll": False, "expressions": False}


class PGSqlState(exp.Expression):
    """Represents the SQLSTATE condition, optionally followed by a string literal.

    Examples:
      - SQLSTATE
      - SQLSTATE '22012'

    The optional literal is stored in `this`.
    """

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

        def _parse_statement(self) -> exp.Expr | None:  # type: ignore[override]
            # Let RETURN be handled as a regular statement within this dialect
            if self._curr and self._curr.text.upper() == "RETURN":
                return self._parse_pgreturn()
            # Support top-level LOOP statements within blocks and WHEN bodies
            if self._curr and self._curr.text.upper() == "LOOP":
                return self._parse_pgloop()
            # Support EXIT [label] [WHEN expr]; anywhere similar to LOOP
            if self._curr and self._curr.text.upper() == "EXIT":
                return self._parse_pgexit()
            # Support CONTINUE [label] [WHEN expr]; anywhere similar to EXIT
            if self._curr and self._curr.text.upper() == "CONTINUE":
                return self._parse_pgcontinue()
            # Support OPEN cursorvar [ [ NO ] SCROLL ] FOR query; anywhere
            if self._curr and self._curr.text.upper() == "OPEN":
                return self._parse_pgopen()
            return super()._parse_statement()

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

        def _parse_pgopen(self) -> PGOpenCursor:
            # Consume OPEN keyword
            if not self._match_texts("OPEN"):
                self.raise_error("Expected OPEN")

            # Cursor variable identifier
            cursor = self._parse_id_var()

            # Bound cursor with positional arguments: OPEN c(<args>)
            if self._match(TokenType.L_PAREN, advance=False):
                args = self._parse_wrapped_csv(self._parse_expression)
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
            PGReturn: lambda self, e: self.pgreturn_sql(e),
            PGExit: lambda self, e: self.pgexit_sql(e),
            PGContinue: lambda self, e: self.pgcontinue_sql(e),
            PGOpenCursor: lambda self, e: self.pgopencursor_sql(e),
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
        def pgothers_sql(self, expression: exp.Expression) -> str:  # type: ignore[override]
            return "OTHERS"

        # Auto-discovered generator for PGSqlState
        def pgsqlstate_sql(self, expression: exp.Expression) -> str:  # type: ignore[override]
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

        def pgloop_sql(self, expression: PGLoop) -> str:
            body_sql = " ".join(f"{self.sql(stmt)};" for stmt in expression.expressions)
            # Render exactly: LOOP <stmts>; END LOOP
            if body_sql:
                return f"LOOP {body_sql} END LOOP"
            return "LOOP END LOOP"

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


plpgsql = PlPgSQL
