from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, replace, InitVar

import networkx as nx
from sqlglot import exp

from sqlleaf import util, mappings, sqlglot_lineage, exception
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
        # Called via replace() or if a new object is instantiated
        if new_data_type:
            expr_type = new_data_type
        else:
            if isinstance(self.expr, exp.ColumnDef):
                expr_type = self.expr.kind
            elif (not self.expr.type or self.expr.type == exp.DataType.Type.UNKNOWN) and self.expr.parent:
                expr_type = self.expr.parent.type
            else:
                expr_type = self.expr.type

        unwrapped_expr = util.unwrap_expression(self.expr)

        object.__setattr__(self, "data_type", expr_type)
        object.__setattr__(self, "expr", unwrapped_expr)


@dataclass(frozen=True)
class NodeContext:
    statement_index: str            # The position of this query inside a list of queries, e.g. SELECT 'a'; SELECT 'b' - a=0, b=1
    select_index: int = 0           # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b') - a=0, b=1
    function_depth: int = 0         # The depth of the function: e.g. SELECT UPPER(LOWER('a')) - LOWER=0, UPPER=1
    function_arg_index: int = 0     # The argument of a function: e.g. SELECT my.func('a', 'b') - a=0, b=1
    node_depth: int = 0             # The depth of a subquery, e.g. WITH cte AS ( SELECT 'a' ) SELECT 'a' - The first a=1, second a=0
