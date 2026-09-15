from __future__ import annotations

from sqlglot import exp


class PGBlock(exp.Block):
    """A BEGIN ... END block."""
    arg_types = {
        "expressions": False,
        "begin": False,
        "declare": False,
        "exception": False,
    }


class PGPerform(exp.Select):
    """A PERFORM statement."""


class PGDeclareItem(exp.DeclareItem):
    """A variable declaration item inside a DECLARE section."""
    arg_types = {
        **exp.DeclareItem.arg_types,
        "expression": False,
        "value": False,
        "assign": False,
        "constant": False,
        "collate": False,
        "not_null": False,
        "alias_for": False,
        "cursor": False,
        "scroll": False,
        "cursor_args": False,
        "query": False,
    }


class PGTypeRef(exp.Expression):
    """A `<reference>%TYPE` or `<reference>%ROWTYPE` type expression used in DECLARE items."""
    arg_types = {"this": True, "array": False, "rowtype": False}


class PGCursorArg(exp.Expression):
    """A cursor argument declaration."""
    arg_types = {"this": True, "kind": True}


class PGException(exp.Expression):
    """An EXCEPTION section."""
    arg_types = {"whens": True}


class PGWhen(exp.Expression):
    """A WHEN ... THEN ... entry inside an EXCEPTION section."""
    arg_types = {"condition": True, "then": True}


class PGCase(exp.CaseStatement):
    """A CASE statement."""


class PGIfBranch(exp.Expression):
    """An IF/ELSIF branch."""
    arg_types = {"condition": True, "then": True}


class PGIf(exp.CaseStatement):
    """An IF statement."""


class PGLoop(exp.LoopBlock):
    """A LOOP statement."""


class PGForIn(exp.Expression):
    """A FOR statement."""
    arg_types = {
        "this": True,
        "query": False,
        "reverse": False,
        "start": False,
        "end": False,
        "step": False,
        "expressions": False,
        "label": False,
    }


class PGCursorCall(exp.Expression):
    """A bound cursor invocation."""
    arg_types = {
        "this": True,
        "expressions": False,
    }


class PGForEach(exp.Expression):
    """A FOREACH statement."""
    arg_types = {
        "this": True,
        "slice": False,
        "expression": True,
        "expressions": False,
        "label": False,
    }


class PGExit(exp.Leave):
    """An EXIT statement."""
    arg_types = {"this": False, "when": False}


class PGContinue(exp.Iterate):
    """A CONTINUE statement.
    """
    arg_types = {"this": False, "when": False}


class PGRaise(exp.Expression):
    """A RAISE statement."""

    arg_types = {
        "level": False,
        "message": False,
        "expressions": False,
        "condition": False,
        "sqlstate": False,
        "using": False,
    }


class PGAssert(exp.Expression):
    """An ASSERT statement."""
    arg_types = {"condition": True, "message": False}


class PGGetDiagnostics(exp.Expression):
    """A GET DIAGNOSTICS statement."""
    arg_types = {"current": False, "stacked": False, "expressions": True}


class PGOpenCursor(exp.Expression):
    """An OPEN cursor statement."""
    arg_types = {"this": True, "expression": False, "scroll": False, "expressions": False}


class PGFetch(exp.Fetch):
    """A FETCH statement."""
    arg_types = {
        **exp.Fetch.arg_types,
        "this": True,
        "expressions": True,
        "preposition": False,
    }


class PGExecute(exp.Execute):
    """A dynamic EXECUTE statement."""
    arg_types = {
        **exp.Execute.arg_types,
        "strict": False,
        "using": False,
    }


class PGInto(exp.Into):
    """An INTO clause."""
    arg_types = {
        **exp.Into.arg_types,
        "strict": False,
    }


class PGReturning(exp.Returning):
    """A RETURNING clause that may carry an INTO [STRICT] target list.

    The existing `into` argument will hold a `PGInto` instance when present.
    """
    # Inherit arg_types from exp.Returning


class PGMove(exp.Expression):
    """A MOVE statement."""
    arg_types = {
        "this": True,
        "direction": False,
        "preposition": False,
    }


class PGClose(exp.Expression):
    """A CLOSE cursor statement."""
    arg_types = {"this": True}


class PGNext(exp.Expression):
    """The NEXT direction."""
    arg_types = {"this": False}


class PGPrior(exp.Expression):
    """The PRIOR direction."""
    arg_types = {"this": False}


class PGFirst(exp.Expression):
    """The FIRST direction."""
    arg_types = {"this": False}


class PGLast(exp.Expression):
    """The LAST direction."""
    arg_types = {"this": False}


class PGForward(exp.Expression):
    """The FORWARD direction."""
    arg_types = {"this": False, "all": False}


class PGBackward(exp.Expression):
    """The BACKWARD direction."""
    arg_types = {"this": False, "all": False}


class PGAbsolute(exp.Expression):
    """The ABSOLUTE <count> direction."""
    arg_types = {"this": True}


class PGRelative(exp.Expression):
    """The RELATIVE <count> direction."""
    arg_types = {"this": True}


class PGAll(exp.Expression):
    """The ALL direction."""
    arg_types = {"this": False}


class PGSqlState(exp.Expression):
    """The SQLSTATE statement."""
    arg_types = {"this": False}


class PGFound(exp.Expression):
    """The special PL/pgSQL boolean status variable FOUND."""
    arg_types = {"this": False}


class PGUpdate(exp.Update):
    """An UPDATE statement with optional WHERE CURRENT OF cursor."""
    arg_types = {**exp.Update.arg_types, "current_of": False}


class PGDelete(exp.Delete):
    """A DELETE statement with optional WHERE CURRENT OF cursor."""
    arg_types = {**exp.Delete.arg_types, "current_of": False}


class PGReturn(exp.Return):
    """A RETURN statement."""
    arg_types = {"this": False, "query": False, "next": False}


class PGOthers(exp.Expression):
    """The OTHERS keyword in EXCEPTION WHEN OTHERS THEN ..."""
    arg_types = {"this": False}
