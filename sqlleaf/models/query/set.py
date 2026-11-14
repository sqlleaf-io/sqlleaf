from __future__ import annotations

import sqlglot
from sqlglot import exp, TokenType

from sqlleaf import mappings
from sqlleaf.dialects.base import DialectConfig
from sqlleaf.models.query.base import Query


class SetQuery(Query):
    """
    Represents a SQL SET statement, which defines session variables.

    This can take several forms, depending on the dialect:
    - SET a = 10;
    - SET (a, b) = (10, 20);
    - SET (a, b) = (SELECT x, y FROM table);

    This class extracts these variables and stores them in the ObjectMapping
    so they can be substituted into subsequent queries in the same session.

    Postgres 'SET search_path' is also handled here. It changes the current user catalog
    instead of storing a session variable.
    """
    KIND = "set"

    def __init__(self, expr: exp.Set | exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
            skip_type_annotation=True,
        )
        self._collect_variables()

    def _resolve_session_variable(self, rhs: exp.Expr) -> exp.Expr:
        """
        Resolve MySQL-style session variable references within an expression's RHS.

        Replaces occurrences of Parameter(Var(name)) with a COPY of the already
        stored session variable value when present. Leaves other parameter types
        (e.g., bind parameters) untouched.
        """
        def _replace(node: exp.Expr) -> exp.Expr:
            # In MySQL, ":=" is an assignment operator that returns the right-hand value.
            # This is different from the "=" assignment operator.
            # For RHS evaluation inside SET, we should treat it as a pure value expression
            # and ignore its side-effect. Example:
            #   SET @a := 100, @b = @a := 200;
            # Here, @b should become 200 (the RHS value), without mutating @a again.
            if self.dialect == "mysql" and isinstance(node, exp.PropertyEQ):
                return node.expression.copy()

            if isinstance(node, exp.Parameter) and isinstance(node.this, exp.Var):
                if not self.dialect == "mysql":
                    return node

                name = node.this.name
                existing = self.object_mapping.session_variables.get(name)
                if existing is not None:
                    return existing.copy()
                # Undefined session variables in MySQL are NULL
                return exp.Null()
            return node

        # Use sqlglot's transform to produce a new tree with replacements.
        return rhs.transform(_replace, copy=True)

    def _set_search_path(self, schemas: list[str]) -> None:
        """
        Point the current user catalog at the first schema of the search path.
        The session user's schema ('$user') is unknown, so it is skipped.
        """
        candidates = [schema for schema in schemas if schema != "$user"]
        if candidates:
            self.object_mapping.current_user_catalog = candidates[0]

    def _reset_search_path(self) -> None:
        """
        Restore the current user catalog to the dialect default, as 'SET search_path TO DEFAULT' does.
        """
        self.object_mapping.current_user_catalog = DialectConfig(self.dialect).DEFAULT_USER_CATALOG

    def _collect_set_command(self):
        """
        Handles 'SET [SESSION] search_path = a, b' which sqlglot parses as a raw Command.
        """
        tokens = sqlglot.tokenize(self.statement.sql(dialect=self.dialect), dialect=self.dialect)[1:]
        if tokens and tokens[0].token_type == TokenType.SESSION:
            tokens = tokens[1:]
        if len(tokens) < 3 or tokens[0].text.lower() != "search_path":
            return

        operator, values = tokens[1], tokens[2:]
        if operator.token_type != TokenType.EQ and operator.text.upper() != "TO":
            return

        if len(values) == 1 and values[0].token_type == TokenType.DEFAULT:
            self._reset_search_path()
            return

        schemas = [token.text.lower() for token in values if token.token_type != TokenType.COMMA]
        self._set_search_path(schemas)

    def _collect_variables(self):
        """
        Extracts session variables from the SET statement and store them inside the object mapping.
        """
        if self.dialect == "postgres" and isinstance(self.statement, exp.Command):
            self._collect_set_command()
            return

        for expression in self.statement.expressions:
            eq_expr = expression.this if isinstance(expression, exp.SetItem) else expression
            if not isinstance(eq_expr, exp.EQ):
                continue

            left, right = eq_expr.left, eq_expr.right
            if isinstance(left, exp.Column) and left.name.lower() == "search_path":
                if isinstance(right, exp.Var) and right.name.upper() == "DEFAULT":
                    self._reset_search_path()
                else:
                    self._set_search_path([right.name])
            elif isinstance(left, exp.Tuple):
                # SET (a, b) = (10, 20)  or  SET (a, b) = (SELECT ...)
                names = [col.name for col in left.expressions]
                if isinstance(right, exp.Tuple):
                    for name, value in zip(names, right.expressions):
                        self.object_mapping.session_variables[name] = self._resolve_session_variable(value)
                else:
                    # A subquery. Clone it for each variable, and assign it to each
                    # Example: SET (a, b) = (SELECT col1, col2 FROM t)
                    # This will store:
                    #   a -> (SELECT col1 FROM t)
                    #   b -> (SELECT col2 FROM t)
                    if isinstance(right, exp.Subquery) and isinstance(right.this, exp.Select):
                        select_cols = right.this.expressions

                        for i, name in enumerate(names):
                            cloned = right.copy()
                            if i < len(select_cols):
                                cloned.this.set("expressions", [select_cols[i].copy()])

                            # Map the variable name to its corresponding single-column subquery
                            self.object_mapping.session_variables[name] = self._resolve_session_variable(cloned)
                    else:
                        for name in names:
                            self.object_mapping.session_variables[name] = self._resolve_session_variable(right)
            else:
                # SET a = <expr>
                name = left.name
                self.object_mapping.session_variables[name] = self._resolve_session_variable(right)
