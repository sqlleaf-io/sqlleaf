from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
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
    """
    KIND = "set"

    def __init__(self, expr: exp.Set, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=None,
            skip_type_annotation=True,
        )
        self._collect()

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

    def _collect(self):
        """
        Extracts session variables from the SET statement.
        """
        for expression in self.statement.expressions:
            eq_expr = expression.this if isinstance(expression, exp.SetItem) else expression
            if not isinstance(eq_expr, exp.EQ):
                continue

            left, right = eq_expr.left, eq_expr.right
            if isinstance(left, exp.Tuple):
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
