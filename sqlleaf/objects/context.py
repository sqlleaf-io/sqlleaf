from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, InitVar

import networkx as nx
from sqlglot import exp

from sqlleaf import util, mappings, sqlglot_lineage

if t.TYPE_CHECKING:
    from sqlleaf.objects.query_types import Query
    from sqlleaf.objects.node_types import NodeAttributes

logger = logging.getLogger("sqleaf")


@dataclass(frozen=True)
class ProcessorContext:
    graph: nx.MultiDiGraph
    object_mapping: mappings.ObjectMapping
    query: Query
    expr: exp.Expression
    data_type: exp.DataType = None
    node: sqlglot_lineage.Node = None
    child_node_attrs: NodeAttributes = None
    # Override the data_type if needed
    new_data_type: InitVar[exp.DataType] = None

    def __post_init__(self, new_data_type: exp.DataType = None):
        """
        Called via replace() or if a new object is instantiated
        """
        expr_type = new_data_type if new_data_type else self.get_expr_type(self.expr)
        unwrapped_expr = util.unwrap_expression(self.expr)

        object.__setattr__(self, "data_type", expr_type)
        object.__setattr__(self, "expr", unwrapped_expr)

    def get_expr_type(self, expr: exp.Expression) -> exp.DataType:
        """
        Determine the expression's data type. If it's missing, use an ancestor's data type.
        """
        is_missing_type: t.Callable[[exp.Expression], bool] = lambda x: not (x.type or x.is_type(exp.DataType.Type.UNKNOWN))

        if isinstance(expr, exp.ColumnDef):
            return expr.kind
        elif is_missing_type(expr) and expr.parent:
            # Use an ancestor's type
            parent = expr.parent
            while parent:
                if not is_missing_type(parent):
                    return parent.type
                parent = parent.parent

            return expr.parent.type
        return expr.type


@dataclass(frozen=True)
class NodeContext:
    # The position of this query inside a list of queries, e.g. SELECT 'a'; SELECT 'b' -> a=0, b=1
    statement_index: str

    # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b') -> a=0, b=1
    select_index: int = 0

    # The depth of the function: e.g. SELECT UPPER(LOWER('a')) -> LOWER=0, UPPER=1
    function_depth: int = 0

    # The argument of a function: e.g. SELECT my.func('a', 'b') -> a=0, b=1
    function_arg_index: int = 0

    # The depth of a subquery, e.g. WITH cte AS ( SELECT 'a' ) SELECT 'a' -> The first a=1, second a=0
    node_depth: int = 0
