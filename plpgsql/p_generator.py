from __future__ import annotations

from sqlglot.generators.postgres import PostgresGenerator
from plpgsql.classes import *


class Generator(PostgresGenerator):
    # Keep explicit TRANSFORMS to adhere to project guidance for this experimental dialect.
    TRANSFORMS = {
        **getattr(PostgresGenerator, "TRANSFORMS", {}),
        PGBlock: lambda self, e: self.pgblock_sql(e),
        PGDeclare: lambda self, e: self.pgdeclare_sql(e),
        PGDeclareItem: lambda self, e: self.pgdeclareitem_sql(e),
        PGException: lambda self, e: self.pgexception_sql(e),
        PGWhen: lambda self, e: self.pgwhen_sql(e),
        PGIf: lambda self, e: self.pgif_sql(e),
        PGIfBranch: lambda self, e: self.pgifbranch_sql(e),
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
        PGForIn: lambda self, e: self.pgforin_sql(e),
        PGForEach: lambda self, e: self.pgforeach_sql(e),
        PGExecute: lambda self, e: self.pgexecute_sql(e),
        PGGetDiagnostics: lambda self, e: self.pggetdiagnostics_sql(e),
        PGCursorArg: lambda self, e: self.pgcursorarg_sql(e),
    }

    def _loop_control_sql(self, keyword: str, expression: exp.Expression) -> str:
        parts: list[str] = [keyword]
        if expression.args.get("this") is not None:
            parts.append(self.sql(expression.this))
        if expression.args.get("when") is not None:
            parts.append("WHEN")
            parts.append(self.sql(expression.args.get("when")))
        return " ".join(parts)

    # Also expose the auto-discovered method
    def pgblock_sql(self, expression: PGBlock) -> str:
        parts: list[str] = []

        # Render DECLARE section first if present
        declare = expression.args.get("declare")
        if declare and getattr(declare, "expressions", None):
            parts.append(self.sql(declare))

        parts.append("BEGIN")
        for expr in expression.expressions:
            parts.append(self.sql(expr) + ";")

        # Render EXCEPTION section if present
        ex = expression.args.get("exception")
        if ex is not None:
            parts.append(self.sql(ex))

        parts.append("END")
        return " ".join(parts)

    def pgdeclare_sql(self, expression: PGDeclare) -> str:
        items = [self.sql(item) + ";" for item in expression.expressions]
        if not items:
            return "DECLARE"
        return " ".join(["DECLARE", *items])

    def pgdeclareitem_sql(self, expression: PGDeclareItem) -> str:
        name = self.sql(expression.this)
        # Cursor declaration
        if expression.args.get("cursor"):
            parts: list[str] = [name]
            scroll = expression.args.get("scroll")

            if scroll is True:
                parts.append("SCROLL")
            elif scroll is False:
                parts.append("NO SCROLL")

            # CURSOR and optional args
            cursor_args = expression.args.get("cursor_args")
            if cursor_args:
                args_sql = ", ".join(self.sql(a) for a in cursor_args)
                parts.append(f"CURSOR({args_sql})")
            else:
                parts.append("CURSOR")

            # FOR query
            parts.append("FOR")
            parts.append(self.sql(expression.args.get("query")))
            return " ".join(parts)

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

    def pgcursorarg_sql(self, expression: PGCursorArg) -> str:
        kind = self.sql(expression.args.get("kind"))
        kind_render = kind.upper() if kind else ""
        return f"{self.sql(expression.this)} {kind_render}"

    def pgexception_sql(self, expression: "PGException") -> str:
        parts: list[str] = ["EXCEPTION"]
        for when in expression.args.get("whens") or []:
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
        body_sql = " ".join(self.sql(stmt) + ";" for stmt in body)
        return f"WHEN {conds} THEN {body_sql}"

    def pgif_sql(self, expression: PGIf) -> str:
        branches = expression.args.get("ifs") or []
        parts: list[str] = []
        for i, branch in enumerate(branches):
            keyword = "IF" if i == 0 else "ELSIF"
            parts.append(self._pgifbranch_sql(branch, keyword))

        default = expression.args.get("default")
        if default is not None:
            body = " ".join(self.sql(stmt) + ";" for stmt in default)
            parts.append(f"ELSE {body}")

        parts.append("END IF")
        return " ".join(parts)

    def _pgifbranch_sql(self, branch: PGIfBranch, keyword: str) -> str:
        cond = self.sql(branch.args.get("condition"))
        body = " ".join(self.sql(stmt) + ";" for stmt in branch.args.get("then"))
        return f"{keyword} {cond} THEN {body}"

    def pgifbranch_sql(self, expression: PGIfBranch) -> str:
        # Standalone rendering (defaults to IF); PGIf normally supplies the keyword.
        return self._pgifbranch_sql(expression, "IF")

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

    def pgforin_sql(self, expression: PGForIn) -> str:
        target_sql = self.sql(expression.this)
        body_sql = " ".join(f"{self.sql(stmt)};" for stmt in expression.expressions)
        label = expression.args.get("label")
        suffix = f" {self.sql(label)}" if label is not None else ""

        query = expression.args.get("query")
        if query is not None:
            header = f"FOR {target_sql} IN {self.sql(query)} LOOP"
        else:
            reverse = "REVERSE " if expression.args.get("reverse") else ""
            start_sql = self.sql(expression.args.get("start"))
            end_sql = self.sql(expression.args.get("end"))
            step = expression.args.get("step")
            by_sql = f" BY {self.sql(step)}" if step is not None else ""
            header = f"FOR {target_sql} IN {reverse}{start_sql}..{end_sql}{by_sql} LOOP"

        if body_sql:
            return f"{header} {body_sql} END LOOP{suffix}"
        return f"{header} END LOOP{suffix}"

    def pgforeach_sql(self, expression: PGForEach) -> str:
        target_sql = self.sql(expression.this)
        array_sql = self.sql(expression.args.get("expression"))
        body_sql = " ".join(f"{self.sql(stmt)};" for stmt in expression.expressions)

        slice_expr = expression.args.get("slice")
        slice_sql = f" SLICE {self.sql(slice_expr)}" if slice_expr is not None else ""

        label = expression.args.get("label")
        suffix = f" {self.sql(label)}" if label is not None else ""

        header = f"FOREACH {target_sql}{slice_sql} IN ARRAY {array_sql} LOOP"
        if body_sql:
            return f"{header} {body_sql} END LOOP{suffix}"
        return f"{header} END LOOP{suffix}"

    def pgexit_sql(self, expression: PGExit) -> str:
        return self._loop_control_sql("EXIT", expression)

    def pgcontinue_sql(self, expression: PGContinue) -> str:
        return self._loop_control_sql("CONTINUE", expression)

    def _direction_and_cursor_sql(self, expression: exp.Expression) -> str:
        dir_expr = expression.args.get("direction")
        if dir_expr is not None:
            prep = expression.args.get("preposition") or "FROM"
            return f"{self.sql(dir_expr)} {prep} {self.sql(expression.this)}"
        return self.sql(expression.this)

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

    # Auto-discovered generator for AssignArg (always PL/pgSQL ':=')
    def assignarg_sql(self, expression: AssignArg) -> str:
        return self.binary(expression, ":=")

    def pgfetch_sql(self, expression: PGFetch) -> str:
        targets_sql = ", ".join(self.sql(e) for e in expression.expressions)
        frag = self._direction_and_cursor_sql(expression)
        return f"FETCH {frag} INTO {targets_sql}"

    def pgmove_sql(self, expression: "PGMove") -> str:
        frag = self._direction_and_cursor_sql(expression)
        return f"MOVE {frag}"

    def pgclose_sql(self, expression: "PGClose") -> str:
        return f"CLOSE {self.sql(expression.this)}"

    def pgexecute_sql(self, expression: PGExecute) -> str:
        parts: list[str] = ["EXECUTE", self.sql(expression.this)]

        targets = expression.args.get("expressions")
        if targets:
            into = "INTO STRICT" if expression.args.get("strict") else "INTO"
            parts.append(f"{into} " + ", ".join(self.sql(t) for t in targets))

        using_args = expression.args.get("using")
        if using_args:
            parts.append("USING " + ", ".join(self.sql(a) for a in using_args))

        return " ".join(parts)

    def pggetdiagnostics_sql(self, expression: PGGetDiagnostics) -> str:
        parts: list[str] = ["GET"]
        if expression.args.get("current"):
            parts.append("CURRENT")
        elif expression.args.get("stacked"):
            parts.append("STACKED")
        parts.append("DIAGNOSTICS")

        assigns = expression.expressions or []
        assigns_sql = ", ".join(self.sql(a) for a in assigns)
        parts.append(assigns_sql)
        return " ".join(parts)

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
