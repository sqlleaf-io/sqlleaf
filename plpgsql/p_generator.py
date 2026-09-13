from __future__ import annotations

from sqlglot import exp
from sqlglot.generators.postgres import PostgresGenerator
from plpgsql.classes import *


class Generator(PostgresGenerator):
    # Keep explicit TRANSFORMS to adhere to project guidance for this experimental dialect.
    TRANSFORMS = {
        **PostgresGenerator.TRANSFORMS,
        PGBlock: lambda self, e: self.pgblock_sql(e),
        # PGDeclare: lambda self, e: self.pgdeclare_sql(e),
        exp.Declare: lambda self, e: self.pgdeclare_sql(e),
        PGDeclareItem: lambda self, e: self.pgdeclareitem_sql(e),
        PGException: lambda self, e: self.pgexception_sql(e),
        PGWhen: lambda self, e: self.pgwhen_sql(e),
        PGIf: lambda self, e: self.pgif_sql(e),
        PGIfBranch: lambda self, e: self.pgifbranch_sql(e),
        PGLoop: lambda self, e: self.pgloop_sql(e),
        # PGWhile: lambda self, e: self.pgwhile_sql(e),
        PGReturn: lambda self, e: self.pgreturn_sql(e),
        PGExit: lambda self, e: self.pgexit_sql(e),
        PGContinue: lambda self, e: self.pgcontinue_sql(e),
        PGRaise: lambda self, e: self.pgraise_sql(e),
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
        PGCursorCall: lambda self, e: self.pgcursorcall_sql(e),
        PGFound: lambda self, e: self.pgfound_sql(e),
        PGOthers: lambda self , e: self.pgothers_sql(e),
        PGPerform: lambda self , e: self.pgperform_sql(e),
    }

    def _loop_control_sql(self, keyword: str, expression: exp.Expression) -> str:
        sql = keyword
        if expression.args.get("this") is not None:
            sql += self.seg(self.sql(expression, "this"))
        if expression.args.get("when") is not None:
            sql += self.seg("WHEN")
            sql += self.seg(self.sql(expression, "when"))
        return sql

    # Also expose the auto-discovered method
    def pgblock_sql(self, expression: PGBlock) -> str:
        sql = ""

        # DECLARE section first if present
        declare = expression.args.get("declare")
        if declare and declare.expressions:
            sql += self.sql(declare) + self.sep()

        # BEGIN ... statements ... [EXCEPTION ...] END
        sql += "BEGIN"

        if expression.expressions:
            body_sql = self.expressions(sqls=[self.sql(e) for e in expression.expressions], sep=f";{self.sep()}")
            sql += self.seg(body_sql + ";")

        ex = expression.args.get("exception")
        if ex is not None:
            sql += self.seg(self.sql(ex))

        sql += self.seg("END")
        return sql

    def pgperform_sql(self, expression: PGPerform) -> str:
        select = exp.Select(**expression.args)
        select_sql = self.select_sql(select)
        return select_sql.replace("SELECT", "PERFORM", 1)

    def pgdeclare_sql(self, expression: exp.Declare) -> str:
        # Render each item separated by semicolons; keep a final trailing semicolon
        if not expression.expressions:
            return "DECLARE"
        items_sql = self.expressions(sqls=[self.sql(item) for item in expression.expressions], sep=f";{self.sep()}")
        return "DECLARE" + self.seg(items_sql + ";")

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
                parts.append(self.func("CURSOR", *cursor_args))
            else:
                parts.append("CURSOR")

            # FOR query
            parts.append("FOR")
            parts.append(self.sql(expression.args.get("query")))
            return " ".join(parts)

        # Handle alias variant early: name ALIAS FOR $n
        if expression.args.get("alias_for"):
            target = self.sql(expression.args.get("expression"))
            return name + self.seg("ALIAS") + self.seg("FOR") + self.seg(target)

        typ = self.sql(expression.args.get("kind")) if expression.args.get("kind") is not None else ""
        # Normalize type rendering to uppercase to match Postgres style in tests
        typ_render = typ.upper() if typ else ""
        const_kw = " CONSTANT" if expression.args.get("constant") else ""
        collate = expression.args.get("collate")
        collate_sql = (self.seg("COLLATE") + self.seg(self.sql(collate))) if collate is not None else ""
        not_null_sql = self.seg("NOT NULL") if expression.args.get("not_null") else ""
        init = expression.args.get("expression")

        if init is not None and expression.args.get("default"):
            return (
                name
                + const_kw
                + (self.seg(typ_render) if typ_render else "")
                + collate_sql
                + not_null_sql
                + self.seg("DEFAULT")
                + self.seg(self.sql(init))
            )

        if init is not None:
            op = expression.args.get("assign") or ":="
            return (
                name
                + const_kw
                + (self.seg(typ_render) if typ_render else "")
                + collate_sql
                + not_null_sql
                + self.seg(op)
                + self.seg(self.sql(init))
            )

        return name + const_kw + (self.seg(typ_render) if typ_render else "") + collate_sql + not_null_sql

    def pgcursorarg_sql(self, expression: PGCursorArg) -> str:
        kind = self.sql(expression.args.get("kind"))
        kind_render = kind.upper() if kind else ""
        return self.sql(expression.this) + (self.seg(kind_render) if kind_render else "")

    def pgexception_sql(self, expression: "PGException") -> str:
        whens = expression.args.get("whens") or []
        sql = "EXCEPTION"
        if whens:
            sql += self.seg(self.expressions(sqls=[self.sql(w) for w in whens], sep=self.sep()))
        return sql

    def pgwhen_sql(self, expression: "PGWhen") -> str:
        # Prefer the normal generator dispatch for conditions
        condition = expression.args.get("condition")
        conds = self.sql(condition) if condition is not None else ""
        body = expression.args.get("then") or []
        body_sql = self.expressions(sqls=[self.sql(stmt) for stmt in body], sep=f";{self.sep()}")
        if body_sql:
            body_sql += ";"
        return "WHEN" + (self.seg(conds) if conds else "") + self.seg("THEN") + (self.seg(body_sql) if body_sql else "")

    def pgif_sql(self, expression: PGIf) -> str:
        branches = expression.args.get("ifs") or []
        sql_parts: list[str] = []
        for i, branch in enumerate(branches):
            keyword = "IF" if i == 0 else "ELSIF"
            sql_parts.append(self._pgifbranch_sql(branch, keyword))

        default = expression.args.get("default")
        if default is not None:
            else_body = self.expressions(sqls=[self.sql(stmt) for stmt in default], sep=f";{self.sep()}")
            if else_body:
                else_body += ";"
            sql_parts.append("ELSE" + (self.seg(else_body) if else_body else ""))

        sql_parts.append("END IF")
        return self.sep().join(sql_parts) if self.pretty else " ".join(sql_parts)

    def _pgifbranch_sql(self, branch: PGIfBranch, keyword: str) -> str:
        cond = self.sql(branch, "condition")
        body = self.expressions(sqls=[self.sql(stmt) for stmt in (branch.args.get("then") or [])], sep=f";{self.sep()}")
        if body:
            body += ";"
        return keyword + (self.seg(cond) if cond else "") + self.seg("THEN") + (self.seg(body) if body else "")

    def pgifbranch_sql(self, expression: PGIfBranch) -> str:
        # Standalone rendering (defaults to IF); PGIf normally supplies the keyword.
        return self._pgifbranch_sql(expression, "IF")

    # Auto-discovered generator for PGOthers
    def pgothers_sql(self, expression: exp.Expression) -> str:
        return "OTHERS"

    # Auto-discovered generator for PGSqlState
    def pgsqlstate_sql(self, expression: exp.Expression) -> str:
        value = expression.this
        if value is not None:
            return "SQLSTATE" + self.seg(self.sql(value))
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

        value = expression.this
        if value is not None:
            return f"RETURN {self.sql(value)}"
        return "RETURN"

    # Shared Return node renderer (for interoperability)
    def return_sql(self, expression: exp.Return) -> str:
        value = expression.this
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
        body = expression.args.get("body") or []
        body_sql = " ".join(f"{self.sql(stmt)};" for stmt in body)
        label = expression.args.get("label")
        suffix = f" {self.sql(label)}" if label is not None else ""
        # Render exactly: LOOP <stmts>; END LOOP [label]
        if body_sql:
            return f"LOOP {body_sql} END LOOP{suffix}"
        return f"LOOP END LOOP{suffix}"

    def whileblock_sql(self, expression: exp.WhileBlock) -> str:
        cond_sql = self.sql(expression.this)
        body = expression.args.get("body") or []
        body_sql = " ".join(f"{self.sql(stmt)};" for stmt in body)
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

    def pgcursorcall_sql(self, expression: PGCursorCall) -> str:
        cursor_sql = self.sql(expression.this)
        args = expression.args.get("expressions")
        if args:
            return f"{cursor_sql}({', '.join(self.sql(arg) for arg in args)})"
        return cursor_sql

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

    # Shared node for EXIT/LEAVE
    def leave_sql(self, expression: exp.Leave) -> str:
        return self._loop_control_sql("EXIT", expression)

    # Shared node for CONTINUE/ITERATE
    def iterate_sql(self, expression: exp.Iterate) -> str:
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
        if expression.expressions:
            args_sql = ", ".join(self.sql(arg) for arg in expression.expressions)
            name_sql = f"{name_sql}({args_sql})"
        return f"OPEN {name_sql}"

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

    def pgfound_sql(self, expression: PGFound) -> str:
        return "FOUND"

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
