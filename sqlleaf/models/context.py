from __future__ import annotations

import logging
import typing as t
from dataclasses import InitVar, dataclass

import networkx as nx
from sqlglot import exp
from sqlglot.optimizer import Scope, traverse_scope

from sqlleaf import util
from sqlleaf.typing import TableOrScopeType

logger = logging.getLogger("sqlleaf")


class ScopePositions:
    def __init__(self):
        self.positions: t.Dict[int, t.Dict[int, int]] = {}

    def get_scope_for_expr(self, expr: exp.Expr) -> dict[int, int]:
        return self.positions[id(expr)]

    def calculate(self, scope: Scope) -> None:
        """
        Determine the height and width of every scope (SELECT statement) in the query's expression tree.
        This iterates over every expression in the tree via Depth-First Search, looking for scopes.
        """
        root_expr = scope.expression.root()
        scopes = {id(scope.expression): scope for scope in list(traverse_scope(root_expr))}

        # For each height, map to the current width
        heights_to_widths = {}
        expr_ids_to_positions = {}
        stack = [(root_expr, 1)]

        while stack:
            node, h = stack.pop()
            node_id = id(node)

            if node_id in scopes:
                logger.debug(f"Found scope expr ({node.__class__.__name__}): {node.sql()}")

                if not expr_ids_to_positions:  # Root node
                    expr_ids_to_positions[node_id] = (0, 0)
                    heights_to_widths[0] = 0
                else:
                    # Track the width across varying heights
                    w = heights_to_widths.get(h, 0)
                    expr_ids_to_positions[node_id] = (h, w)
                    heights_to_widths[h] = w + 1
                    logger.debug(f"Set height={h} width={w}")
                    h = h + 1
                scopes.pop(node_id)

            for v in node.iter_expressions(reverse=True):
                stack.append((v, h))

        self.positions = expr_ids_to_positions


@dataclass(frozen=True)
class GeneratorContext[Q, N]:
    graph: nx.MultiDiGraph
    query: Q
    expr: exp.Expr
    scope: TableOrScopeType
    child_node: N
    scope_positions: ScopePositions = ScopePositions()
    data_type: exp.DataType | None = None
    # Override the data_type if needed
    new_data_type: InitVar[exp.DataType | None] = None

    def __post_init__(self, new_data_type: exp.DataType | None = None):
        """
        Called via replace() or if a new object is instantiated
        """
        expr_type = new_data_type if new_data_type else self.get_expr_type(self.expr)
        unwrapped_expr = util.unwrap_expression(self.expr)

        object.__setattr__(self, "data_type", expr_type)
        object.__setattr__(self, "expr", unwrapped_expr)

    def get_child_node(self) -> N:
        assert self.child_node is not None
        return self.child_node

    @staticmethod
    def get_expr_type(expr: exp.Expr) -> exp.DataType:
        """
        Determine the expression's data type. If it's missing, use an ancestor's data type.
        """

        def is_missing_type(x: exp.Expr) -> bool:
            return not (x.type or x.is_type(exp.DType.UNKNOWN.into_expr()))

        if isinstance(expr, exp.ColumnDef):
            return expr.kind or exp.DType.UNKNOWN.into_expr()
        elif is_missing_type(expr) and expr.parent:
            # Use an ancestor's type
            parent = expr.parent
            while parent:
                if not is_missing_type(parent):
                    return t.cast(exp.DataType, parent.type)
                parent = parent.parent

            return t.cast(exp.DataType, expr.parent.type)
        return expr.type or exp.DType.UNKNOWN.into_expr()


@dataclass(frozen=True)
class PositionContext:
    # The position of this query inside a list of queries, e.g. SELECT 'a'; SELECT 'b' -> a=0, b=1
    statement_index: str

    # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b') -> a=0, b=1
    select_index: int = 0

    # The depth of the function: e.g. SELECT UPPER(LOWER('a')) -> LOWER=0, UPPER=1
    function_depth: int = 0

    # The argument of a function: e.g. SELECT my.func('a', 'b') -> a=0, b=1
    function_arg_index: int = 0

    # The depth of a subquery, e.g. WITH cte AS (SELECT 'a') SELECT 'a' -> The first a=1, second a=0
    query_depth: int = 0

    # The width of a subquery, e.g. SELECT 4 + (SELECT 5) + (SELECT 6) -> depth(4)=0, depth(5)=1, depth(6)=1
    query_width: int = 0

    def as_str(self) -> str:
        parts = [
            f"query_depth={self.query_depth}",
            f"query_width={self.query_width}",
            f"statement={self.statement_index}",
            f"select={self.select_index}",
            f"func_depth={self.function_depth}",
            f"func_arg={self.function_arg_index}",
        ]
        return " ".join(parts)
