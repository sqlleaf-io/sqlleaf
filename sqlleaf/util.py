import typing as t
import hashlib

from sqlglot import exp
import networkx as nx


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
    new_list = []
    for l in lst:
        if isinstance(l, list):
            for ll in l:
                new_list.append(ll)
        else:
            new_list.append(l)
    return new_list


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


def find_edge_paths(g: nx.MultiDiGraph, start: str, path: t.List = None, seen: t.Set = None):
    """
    Find all the complete paths in a graph by traversing the descendants of a node until we find
    a node without any descendants.

    This is the same as the regular find_paths(), but we iterate over all the edges between any two nodes
    so that we include all paths.

    For example, given the graph:
        A -> B -> C -> D

    If there are two edges between A->B and two edges between C->D:
           __         __
          /  \       /  \
     --> A    B --> C    D -->
          \__/       \__/

    then traversing all the edges gives:
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D
        A -> B -> C -> D

    Thus we consider each path during traversal, as each likely has slightly different attributes.

    Returns:
        [(A, B, edge_data={x}), (A, B, edge_data={y}), (B, C, edge_data={z}), ...]
    """
    if path is None:
        path = []
    if seen is None:
        seen = {start}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, start, 1)
    if not desc:
        yield path
    else:
        desc = sorted(desc)  # nx.desc() is non-deterministic
        for n in desc:
            if n in seen:
                # TODO: this might be a bug. It's valid to re-visit a node if it's further down in the chain.
                #  e.g. A -> B -> C -> A
                #  This code appears to return A -> B -> C upon reaching C -> A, leaving out edges
                yield path
            else:
                edges = g.get_edge_data(start, n)
                for idx, data in edges.items():
                    hop = data["attrs"]
                    # hop = (start, n, data)
                    yield from find_edge_paths(g, n, path + [hop], seen.union([n]))


def find_edges_downward(g: nx.MultiDiGraph, start: str, seen: t.Set = None, depth: int = 0):
    """
    Traverse the graph, returning any unseen edges.

    Similar to find_edge_paths(), except we return an unseen edge found at each hop, rather than the entire path leading us there.
    """
    if seen is None:
        seen = {start}

    # Get direct descendants
    desc = nx.descendants_at_distance(g, start, 1)

    for n in desc:
        if n not in seen:
            # TODO: this could be a bug similar to the above comment in function
            edges = g.get_edge_data(start, n)
            for idx, data in edges.items():
                hop = data["attrs"]
                # Depth-first search?
                yield depth, hop
                yield from find_edges_downward(g, n, seen.union([n]), depth + 1)


def find_paths(g: nx.MultiDiGraph, start=0, path: t.List = None, seen: t.Set = None):
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


def unwrap_expression(expr: exp.Expression) -> exp.Expression:
    """
    Extract the expression from underneath an Alias or a Paren.
    """
    ex = expr
    while isinstance(ex, (exp.Alias, exp.Paren)):
        ex = ex.unalias().unnest()
    return ex


def copy_expression(expr: exp.Expression) -> exp.Expression:
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
                    return new_ex


def column_def_to_column(column_def: exp.ColumnDef, parent_table: exp.Table = None) -> exp.Column:
    """
    Convert an exp.ColumnDef to a exp.Column

    Parameters:
        column_def:
        parent_table: a table to copy attributes from (schema, table)
        copy:
    """
    if parent_table:
        table = parent_table
    elif isinstance(column_def.parent, exp.Schema):
        table: exp.Table = column_def.parent.this
    else:
        table: exp.Table = column_def.parent

    col = exp.column(
        column_def.name,
        table=table.name,
        db=table.db or None,
        catalog=table.catalog or None,
    )
    col.type = column_def.kind
    return col


def get_table(expr: exp.Expression) -> exp.Table:
    return expr.find(exp.Table)


def get_function_args(expr: exp.Func):
    function_args = list(expr.args.values())
    function_args = flatten(function_args)
    function_args = [arg for arg in function_args if arg and isinstance(arg, exp.Expression)]
    return function_args
