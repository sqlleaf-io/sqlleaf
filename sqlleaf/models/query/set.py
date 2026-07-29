from __future__ import annotations

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class SetQuery(Query):
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

    def _collect(self):
        for expression in self.statement.expressions:
            eq_expr = expression.this if isinstance(expression, exp.SetItem) else expression
            if not isinstance(eq_expr, exp.EQ):
                continue
            left, right = eq_expr.left, eq_expr.right
            if isinstance(left, exp.Tuple):
                # SET (a, b) = (10, 20)  or  SET (a, b) = (SELECT ...)
                names = [col.name.upper() for col in left.expressions]
                if isinstance(right, exp.Tuple):
                    for name, value in zip(names, right.expressions):
                        self.object_mapping.session_variables[name] = value
                else:  # Subquery — clone it once per variable, keeping only the i-th column
                    if isinstance(right, exp.Subquery) and isinstance(right.this, exp.Select):
                        select_cols = right.this.expressions
                        for i, name in enumerate(names):
                            cloned = right.copy()
                            if i < len(select_cols):
                                cloned.this.set("expressions", [select_cols[i].copy()])
                            self.object_mapping.session_variables[name] = cloned
                    else:
                        for name in names:
                            self.object_mapping.session_variables[name] = right
            else:
                # SET a = <expr>
                name = left.name.upper()
                self.object_mapping.session_variables[name] = right
