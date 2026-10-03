import logging
import typing as t

import sqlglot
from sqlglot import exp, TokenType

from sqlleaf import exception


logger = logging.getLogger("sqlleaf")


def _determine_query_kind(statement: exp.Expr, dialect: str) -> t.Tuple[exp.Expr, str]:
    """
    Determine a query's "kind" from the expression, which maps to how it will be processed.
    """
    if statement.key == "create" and isinstance(statement, exp.Create):
        if statement.kind == "TABLE":
            if isinstance(statement.expression, (exp.Select, exp.Values)) or statement.find(exp.ExecuteAsProperty):
                kind = "ctas"
            else:
                kind = "table"
        else:
            kind = (statement.kind or "").lower()
    elif statement.key == "select" and "into" in statement.args:
        # sqlglot rewrites 'SELECT INTO' to 'CREATE TABLE AS' during parse()
        # but it's not shown until we produce it with sql(), so we re-parse it
        if dialect in ["redshift", "postgres", "mysql"]:
            statement = sqlglot.parse_one(statement.sql(dialect=""), dialect=dialect)
            kind = "ctas"
        else:
            message = f"Expression 'SELECT INTO' has not been implemented yet for dialect: {dialect}"
            raise exception.UnsupportedFeatureError(message=message)
    else:
        kind = statement.key.lower()

    return statement, kind


def _classify_command(stmt: exp.Command, dialect: str) -> tuple[str, bool]:
    """
    Classify an exp.Command node into a (kind, is_supported) pair.
    kind='' means the command is not recognised and should be treated as unsupported.
    """
    if dialect in ["athena", "redshift"] and stmt.name == "UNLOAD":
        return "unload", True
    if dialect == "postgres" and stmt.name == "PREPARE":
        return "prepare", _is_prepare_supported(stmt)
    if dialect == "postgres" and stmt.name == "EXECUTE":
        return "execute", _is_execute_supported(stmt)
    if dialect == "mysql" and stmt.name == "REPLACE":
        return "replace", _is_replace_supported(stmt, dialect)
    if stmt.this.upper() == "CALL":
        return "call", True
    return "", False


def _is_prepare_supported(stmt: exp.Command) -> bool:
    """
    Check if a PREPARE statement for Postgres is supported.
    Syntax: PREPARE name AS statement
    The variant where parameters are provided is not yet supported.
    """
    expression_name = stmt.expression.name
    tokens = sqlglot.tokenize(expression_name, dialect="postgres")

    if len(tokens) < 3:
        raise exception.InvalidQueryError(f"Invalid syntax for PREPARE expression: {stmt.sql(dialect='postgres')}")

    # We cannot process arguments yet
    if tokens[1].token_type != TokenType.ALIAS or tokens[1].text.upper() != "AS":
        if tokens[1].token_type == TokenType.L_PAREN:
            logger.warning("PREPARE with arguments is not currently supported.")
        return False

    # Ensure there's an 'AS' token
    if not any(t.token_type == TokenType.ALIAS and t.text.upper() == "AS" for t in tokens):
        raise exception.InvalidQueryError(f"Could not find 'AS' in PREPARE expression: {expression_name}")

    return True


def _is_execute_supported(stmt: exp.Command) -> bool:
    """
    Check if an EXECUTE statement for Postgres is supported.
    Syntax: EXECUTE name [ ( parameter [, ...] ) ]

    Only the bare-name form (exactly one token, no argument parentheses) is supported.
    If the expression contains more than one token it means arguments were supplied
    (e.g. EXECUTE my_plan(arg1, arg2)), which is not yet handled.
    """
    expression_name = stmt.expression.name
    tokens = sqlglot.tokenize(expression_name, dialect="postgres")

    if not tokens or len(tokens) > 1:
        raise exception.InvalidQueryError(f"Invalid syntax for EXECUTE expression: {stmt.sql(dialect='postgres')}")

    return True


def _is_replace_supported(stmt: exp.Command, dialect: str) -> bool:
    """
    Check if a REPLACE statement is supported.
    Transform to INSERT INTO to verify syntax.
    """
    expression = stmt.args.get("expression")
    new_sql = f"INSERT {expression.this}" if expression else "INSERT"
    try:
        sqlglot.parse_one(new_sql, dialect=dialect)
        return True
    except Exception as e:
        logger.warning(f"Invalid REPLACE statement syntax: {e}")
        return False


