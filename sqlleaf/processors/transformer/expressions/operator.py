from __future__ import annotations

from sqlglot import exp, parse_one


def simplify_operators(statement: exp.Expr, dialect: str, catalog: str) -> None:
    """
    Replace `OPERATOR(pg_catalog.<op>)` with the plain `<op>` operator.

    Examples:
        SELECT 3 OPERATOR(pg_catalog.+) 4                      -> SELECT 3 + 4
        SELECT 'abc' OPERATOR(pg_catalog.||) 'def'             -> SELECT 'abc' || 'def'
        SELECT 3 OPERATOR(pg_catalog.+) 4 OPERATOR(pg_catalog.*) 2 -> SELECT 3 + 4 * 2
    """
    # Process innermost operators first, so that operands are already unwrapped when their parent is rebuilt
    if dialect == "postgres":
        catalog_prefix = f"{catalog}."
        for operator in reversed(list(statement.find_all(exp.Operator))):
            name = operator.args["operator"]
            if not name.startswith(catalog_prefix):
                continue

            symbol = name.removeprefix(catalog_prefix)
            template = parse_one(f"l {symbol} r", read=dialect)
            template.this.replace(operator.this)
            template.expression.replace(operator.expression)

            # Keep the grouping of nested operators, e.g. (3 + 4) * 2 must not become 3 + 4 * 2
            if isinstance(operator.parent, exp.Binary):
                template = exp.Paren(this=template)

            operator.replace(template)
