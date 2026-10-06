import itertools
import re

from sqlglot import exp

# Matches and parses PostgreSQL format() specifiers including position, flags, width, and conversion type.
_SPECIFIER = re.compile(r"%(?:(\d+)\$)?(-)?(?:\*(\d+)\$|(\*)|(\d+))?(.?)", re.DOTALL)
# Matches valid unquoted SQL identifier names composed of lowercase alphanumeric characters and underscores.
_IDENT_SAFE = re.compile(r"^[a-z_][a-z0-9_]*$")

# The keywords were selected from: `SELECT word FROM pg_get_keywords() WHERE catcode IN ('R', 'T') ORDER BY word;`
# These must be explicitly listed because quote_ident() only requires quoting for reserved keywords ('R' and 'T' catcodes), and
# sqlglot's dialect keywords over-quote identifiers, as it includes unreserved keywords and internal parser tokens.
_RESERVED_KEYWORDS = frozenset(
    """
    all analyse analyze and any array as asc asymmetric authorization binary both case cast
    check collate collation column concurrently constraint create cross current_catalog
    current_date current_role current_schema current_time current_timestamp current_user
    default deferrable desc distinct do else end except false fetch for foreign freeze from
    full grant group having ilike in initially inner intersect into is isnull join lateral
    leading left like limit localtime localtimestamp natural not notnull null offset on
    only or order outer overlaps placing primary references returning right select
    session_user similar some symmetric system_user table tablesample then to trailing
    true union unique user using variadic verbose when where window with
    """.split()
)


def simplify_format(sql: exp.Expr, dialect: str) -> str | exp.Expr:
    """Simplify FORMAT(...) expressions in an SQL query string or expression AST.

    Example:
        SELECT FORMAT('Hello %s!', 'World')
        ->
        SELECT 'Hello World!'
    """
    if dialect not in ("postgres", "plpgsql"):
        return sql

    if isinstance(sql, exp.Format):
        return exp.Literal.string(_eval_format(sql))

    if not sql.find(exp.Format):
        return sql

    node = sql.copy()
    for fmt in list(node.find_all(exp.Format))[::-1]:
        fmt.replace(exp.Literal.string(_eval_format(fmt)))
    return node


def pg_format(template: str, *args: object) -> str:
    """Format a template string according to PostgreSQL format() semantics."""
    if "%" not in template:
        return template

    cursor = itertools.count(1)

    def replace(match: re.Match[str]) -> str:
        """Process a single format specifier regex match into its formatted string value."""
        position, flag, width_pos, width_star, width_val, type_char = match.groups()

        if type_char == "%":
            if (
                position is not None
                or flag is not None
                or width_pos is not None
                or width_star is not None
                or width_val is not None
            ):
                raise ValueError('unrecognized format() type specifier "%"')
            return "%"

        if not type_char:
            raise ValueError("unterminated format() type specifier")

        if type_char not in "sLI":
            raise ValueError(f'unrecognized format() type specifier "%{type_char}"')

        # Resolves and validates the format specifier width from positional/star arguments or literal values.
        width = None
        if width_pos is not None:
            w_idx = int(width_pos)
            if w_idx == 0:
                raise ValueError("format specifies argument 0, but arguments are numbered from 1")
        elif width_star is not None:
            w_idx = next(cursor)
        else:
            w_idx = None

        if w_idx is not None:
            if w_idx > len(args):
                raise ValueError("too few arguments for format()")
            w_val = args[w_idx - 1]
            if w_val is None:
                raise ValueError("null width is not allowed")
            w_int = int(w_val)
            if w_int < 0:
                flag = "-"
                w_int = -w_int
            width = w_int
        elif width_val is not None:
            width = int(width_val)

        if position is not None:
            index = int(position)
        else:
            index = next(cursor)

        if index == 0:
            raise ValueError("format specifies argument 0, but arguments are numbered from 1")
        if index > len(args):
            raise ValueError("too few arguments for format()")

        value = args[index - 1]

        if type_char == "s":
            t = _as_text(value)
            rendered = "" if t is None else t
        elif type_char == "L":
            rendered = quote_nullable(value)
        else:
            if value is None:
                raise ValueError("null values cannot be formatted as an SQL identifier")
            rendered = quote_ident(value)

        if width is not None:
            rendered = rendered.ljust(width) if flag == "-" else rendered.rjust(width)

        return rendered

    return _SPECIFIER.sub(replace, template)


def _as_text(value: object) -> str | None:
    """Convert a Python value into its PostgreSQL text representation."""
    if value is None:
        return None
    if value is True:
        return "t"
    if value is False:
        return "f"
    return str(value)


def quote_ident(value: object) -> str | None:
    """Quote a PostgreSQL identifier string if it contains special characters or is a reserved keyword."""
    text = _as_text(value)
    if text is None:
        return None
    if _IDENT_SAFE.match(text) and text not in _RESERVED_KEYWORDS:
        return text
    escaped = text.replace('"', '""')
    return f'"{escaped}"'


def quote_literal(value: object) -> str | None:
    """Quote and escape a string value as a PostgreSQL literal."""
    text = _as_text(value)
    if text is None:
        return None
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def quote_nullable(value: object) -> str:
    """Quote and escape a value as a PostgreSQL literal, returning 'NULL' if the value is None."""
    text = _as_text(value)
    if text is None:
        return "NULL"
    escaped = text.replace("'", "''")
    return f"'{escaped}'"


def _eval_format(node: exp.Format) -> str:
    """Evaluate a Format AST node by resolving its template and arguments."""
    template = _eval_arg(node.this)
    if not isinstance(template, str):
        raise ValueError("format() template must be a string")
    return pg_format(template, *(_eval_arg(arg) for arg in node.expressions))


def _eval_arg(node: exp.Expression | None) -> object:
    """Recursively evaluate an AST expression node into its scalar value."""
    if node is None or isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Format):
        return _eval_format(node)
    if isinstance(node, exp.Boolean):
        return node.this
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        val = node.this
        try:
            return float(val) if "." in val else int(val)
        except ValueError, TypeError:
            return val
    if isinstance(node, exp.Neg):
        val = _eval_arg(node.this)
        return -val if isinstance(val, (int, float)) else f"-{val}"
    if isinstance(node, (exp.Paren, exp.Cast)):
        return _eval_arg(node.this)
    if isinstance(node, exp.Anonymous):
        func_name = node.name.lower()
        if func_name in ("quote_ident", "quote_ident", "quote_literal", "quote_nullable"):
            arg = _eval_arg(node.expressions[0]) if node.expressions else None
            if func_name in ("quote_ident"):
                return quote_ident(arg)
            if func_name == "quote_literal":
                return quote_literal(arg)
            return quote_nullable(arg)
    arg_sql = node.sql(dialect="postgres")
    raise ValueError(f"cannot evaluate format() argument: {arg_sql}")
