from __future__ import annotations

from sqlglot import exp

class PGBlock(exp.Expression):
    """A BEGIN ... END block."""
    arg_types = {"expressions": True, "begin": False, "declare": False, "exception": False}


class PGDeclare(exp.Expression):
    """A DECLARE section."""
    arg_types = {"expressions": True}


class PGDeclareItem(exp.Expression):
    """A variable declaration item inside a DECLARE section."""
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
        "cursor": False,
        "scroll": False,
        "cursor_args": False,
        "query": False,
    }


class PGCursorArg(exp.Expression):
    """A cursor argument declaration."""
    arg_types = {"this": True, "kind": True}


class PGException(exp.Expression):
    """An EXCEPTION section."""
    arg_types = {"whens": True}


class PGWhen(exp.Expression):
    """A WHEN ... THEN ... entry inside an EXCEPTION section."""
    arg_types = {"condition": True, "then": True}


class PGIfBranch(exp.Expression):
    """An IF/ELSIF branch."""
    arg_types = {"condition": True, "then": True}


class PGIf(exp.Expression):
    """An IF statement."""
    arg_types = {"ifs": True, "default": False}


class PGLoop(exp.Expression):
    """A LOOP statement."""
    arg_types = {"expressions": True}


class PGWhile(exp.Expression):
    """A WHILE statement."""
    arg_types = {"this": True, "expressions": True, "label": False}


class PGForIn(exp.Expression):
    """A FOR statement."""
    arg_types = {
        "this": True,
        "query": False,
        "reverse": False,
        "start": False,
        "end": False,
        "step": False,
        "expressions": True,
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
        "expressions": True,
        "label": False,
    }


class PGExit(exp.Expression):
    """An EXIT statement."""
    arg_types = {"this": False, "when": False}


class PGContinue(exp.Expression):
    """A CONTINUE statement."""
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


class PGAssignArg(exp.Expression, exp.Binary):
    """Represents a named argument using `:=` syntax."""
    arg_types = {"this": True, "expression": True, "op": False}


class PGOpenCursor(exp.Expression):
    """An OPEN cursor statement."""
    arg_types = {"this": True, "expression": False, "scroll": False, "expressions": False}


class PGFetch(exp.Expression):
    """A FETCH statement."""
    arg_types = {
        "this": True,
        "expressions": True,
        "direction": False,
        "preposition": False,
    }


class PGExecute(exp.Expression):
    """A dynamic EXECUTE statement."""

    arg_types = {
        "this": True,          # command-string expression (literal / concat / function call)
        "expressions": False,  # INTO target list (list of variables), optional
        "strict": False,       # True when INTO STRICT was used
        "using": False,        # USING expression list, optional
    }


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


class PGReturn(exp.Expression):
    """A RETURN statement."""
    arg_types = {"this": False, "query": False, "next": False}


class PGOthers(exp.Expression):
    """The OTHERS keyword in EXCEPTION WHEN OTHERS THEN ..."""
    arg_types = {"this": False}
