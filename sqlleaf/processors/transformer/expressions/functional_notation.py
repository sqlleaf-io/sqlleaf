from __future__ import annotations

from sqlglot import exp


def rewrite_functional_notation_columns(statement: exp.Expr) -> exp.Expr:
    """
    Rewrite Postgres functional-notation column references from exp.TableColumn to exp.Column.

    Examples:
        SELECT name(source) FROM source      -> SELECT source.name FROM source
        SELECT name(s) AS n FROM source s    -> SELECT s.name AS n FROM source s
    """
    # Convert Anonymous(name)(TableColumn(this=<table ident>)) -> Column(table.name)
    for anon in statement.find_all(exp.Anonymous):
        if len(args := anon.expressions) == 1:
            arg = args[0]
            if isinstance(arg, exp.TableColumn):
                new_col = exp.Column(this=anon.this, table=arg.this)
                anon.replace(new_col)

    return statement
