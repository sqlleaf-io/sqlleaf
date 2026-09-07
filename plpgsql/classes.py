from __future__ import annotations

"""
Example custom dialect that extends Postgres to parse simple PL/pgSQL-style blocks.
"""

from sqlglot import exp

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
    arg_types = {"this": True, "expression": True, "op": False}


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

