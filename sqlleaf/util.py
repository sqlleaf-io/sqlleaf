import logging
import typing as t
import hashlib
from functools import singledispatchmethod
from pathlib import Path

from sqlglot import exp
import networkx as nx

from sqlleaf import exception
from sqlleaf.typing import E

logger = logging.getLogger("sqlleaf")


def unique(sequence: t.List):
    """
    Return a list of unique elements in a list while preserving insertion order.
    """
    seen = set()
    return [x for x in sequence if not (x in seen or seen.add(x))]


def flatten(lst: t.List):
    """
    Flatten a potentially nested list into a single list.
    For example,
        [a, 1, [b, c]]
    returns
        [a, 1, b, c]
    """
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def type_name(typ) -> str:
    """
    Return the name of a type's class.

    Example:
        type_name(sqlglot.class.Expression) -> 'expression'
    """
    return type(typ).__name__.lower()


def chunks(lst, n):
    """
    Yield successive n-sized chunks from lst.
    """
    return [lst[i : i + n] for i in range(0, len(lst), n)]


def short_sha256_hash(text: str):
    return hashlib.md5(text.encode()).hexdigest()[:16]


def long_sha256_hash(text: str):
    return hashlib.md5(text.encode()).hexdigest()


def find_edges_downward(g: nx.MultiDiGraph, node: str, seen: t.Optional[t.Set[str]] = None, depth: int = 0):
    """
    Traverse the graph, returning any unseen edges.

    Similar to find_edges_from_root(), except we return an unseen edge found at each hop, rather than the entire path leading us there.
    """
    if seen is None:
        seen = {node}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, node, 1)

    for n in desc:
        if n not in seen:
            # TODO: this could be a bug similar to the above comment in function
            edges = g.get_edge_data(node, n)
            for idx, data in edges.items():
                hop = data["attrs"]
                # Depth-first search?
                yield depth, hop
                yield from find_edges_downward(g, n, seen.union([n]), depth + 1)


def find_paths(g: nx.MultiDiGraph, start=0, path: t.Optional[t.List[int]] = None, seen: t.Optional[t.Set[int]] = None):
    """
    Find all the complete paths in a graph by traversing the descendants of a node until we find
    a node without any descendants.
    """
    if path is None:
        path = [start]
    if seen is None:
        seen = {start}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, start, 1)
    if not desc:
        yield path
    else:
        for n in desc:
            if n in seen:
                yield path
            else:
                yield from find_paths(g, n, path + [n], seen.union([n]))


def unwrap_expression(expr: E) -> exp.Expr:
    """
    Extract the expression from underneath an Alias or a Paren.
    """
    ex = expr
    while isinstance(ex, (exp.Alias, exp.Paren)):
        ex = ex.unalias()
        if isinstance(ex, (exp.Subquery,)):
            break
        ex = ex.unnest()
    return ex


def copy_expression(expr: E) -> E:
    """
    Copy an expression.

    Unlike sqlglot's copy() method, this preserves the expression's parents.
    """
    for i, ex in enumerate(expr.root().walk()):
        if ex == expr:
            copy_expr = expr.root().copy()
            # Get the equivalent statement in the copy
            for j, new_ex in enumerate(copy_expr.walk()):
                if j == i:
                    return t.cast(E, new_ex)
    return expr


def column_def_to_column(column_def: exp.ColumnDef, parent_table: t.Optional[exp.Table] = None) -> exp.Column:
    """
    Convert an exp.ColumnDef to an exp.Column
    """
    if parent_table:
        table = parent_table
    elif isinstance(column_def.parent, exp.Schema):
        table: exp.Table = column_def.parent.this
    else:
        table = column_def.parent
        assert isinstance(table, exp.Table)

    col = exp.column(
        column_def.name,
        table=table.name,
        db=table.db or None,
        catalog=table.catalog or None,
    )
    col.type = column_def.kind
    return col


def str_to_column_def(name: str) -> exp.ColumnDef:
    """
    Convert a string into a ColumnDef.
    """
    return exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build("UNKNOWN"))


def get_table(expr: exp.Expr) -> exp.Table:
    table = expr.find(exp.Table)
    if table is None:
        raise exception.SqlLeafException(message=f"Could not find an exp.Table in expression: {expr.sql()}")
    return table


def get_function_args(expr: exp.Func):
    function_args = list(expr.args.values())
    function_args = flatten(function_args)
    function_args = [arg for arg in function_args if arg and isinstance(arg, exp.Expr)]
    return function_args


def get_root_nodes(graph: nx.MultiDiGraph) -> t.List[str]:
    """
    Get the root nodes of a graph. A root node has no parents.
    """
    selfloops = []

    def remove_selfloop_edges(n1: str, n2: str, edge_key: int):
        attrs = graph[n1][n2][edge_key]["attrs"]
        if n1 == n2 and attrs:
            if n1 not in selfloops:
                selfloops.append(n1)
            return False
        return True

    # Remove all the selfloop edges so that we can find the root nodes,
    # and then add them back. (This is due to in/out_degree() inclduing them as edges)
    view = nx.subgraph_view(graph, filter_edge=remove_selfloop_edges)
    roots = [
        n
        for n in view.nodes
        if
        # A root node
        (view.in_degree(n) == 0 and view.out_degree(n) > 0)
        or
        # A selfloop
        (n in selfloops and view.degree(n) == 0)
    ]
    logger.debug(f"Found selfloops: {selfloops}")
    return roots


def get_cycles(graph: nx.MultiDiGraph):
    """
    Find all cycles in a graph.
    """
    errors = 0

    for cycle in nx.simple_cycles(graph):
        columns = [col for col in cycle if col.startswith("column")]

        if len(unique(columns)) == 1:
            # A valid cycle. This is a selfloop that passes through another node, e.g. a function.
            first_column = columns[0]
            idx = cycle.index(first_column)
            new_cycle = cycle[idx:] + cycle[:idx] + [first_column]
            logger.debug(f"Found cycle: {new_cycle}")
            cycle = new_cycle
        else:
            if len(columns) == 0:
                logger.error(f"A cycle must contain 1 column node: {cycle}")
                errors = 1
            elif len(unique(columns)) > 1:
                logger.error(f"A cycle cannot contain more than 1 column (found {len(unique(columns))}): {cycle}")
                errors = 1

        yield cycle, errors


def find_property(statement: exp.Create) -> str:
    """
    Get the table/view's property (e.g. TEMPORARY, EXTERNAL, RECURSIVE)
    """
    properties = (exp.TemporaryProperty, exp.ExternalProperty, exp.MaterializedProperty)
    property = ""
    if props := statement.args["properties"]:
        property = str(props.find(properties) or "").lower()
    return property


def get_file_format(file_path: str) -> str:
    file_format = "".join(Path(file_path).suffixes)
    file_format = file_format[1:] if file_format else "UNKNOWN"
    return file_format


class SingleDispatchMethodLogger(singledispatchmethod):
    """
    Override the functools.singledispatchmethod class to print the methods that get called.
    Used for debugging purposes.
    """
    def __get__(self, obj: t.Any, cls: t.Any = None) -> t.Any:
        if obj is None:
            return self

        # Intercept execution and print the types
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            target_type = type(args[0])
            actual_func = self.dispatcher.dispatch(target_type)

            logger.debug(f"Dispatching to: '{getattr(actual_func, '__name__')}' for expr: {type(args[0])}")

            result = actual_func(obj, *args, **kwargs)
            return result

        t.cast(t.Any, wrapper).register = self.register
        return wrapper


singledispatchmethodlogger = SingleDispatchMethodLogger
