import os
import sys

from sqlglot import exp

from sqlleaf.models.node import FunctionNode, N
from sqlleaf.lineage import Hook
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


sql = """
INSERT INTO fruit.processed (name)
SELECT LOWER('hello') AS name;
"""


def test__hooks_no_functions_created(holder):
    hooks = [Hook(name="no_functions", kind=FunctionNode, func=lambda n: None)]
    h = holder(sql=sql, dialect=DIALECT, with_tables=True, hooks=hooks)

    assert h.paths == [['literal["hello"]', "column[fruit.processed.name]"]]
    assert len(h.nodes) == 2
    assert len(h.edges) == 1
    h.lineage.deregister_hooks(hooks)
    assert h.lineage.user_defined_hooks == []


def test__hooks_functions_created(holder):
    hooks = [Hook(name="allow_functions", kind=FunctionNode, func=lambda n: n)]
    h = holder(sql=sql, dialect=DIALECT, with_tables=True, hooks=hooks)

    assert h.paths == [['literal["hello"]', "function[LOWER]", "column[fruit.processed.name]"]]
    assert len(h.nodes) == 3
    assert len(h.edges) == 2
    h.lineage.deregister_hooks(hooks)
    assert h.lineage.user_defined_hooks == []


def test__hooks_functions_created_if_integer_arg(holder):
    sql = """
    INSERT INTO fruit.processed (name, age)
    SELECT LOWER('hello') AS name, MAX(3) FROM fruit.raw;
    """

    def only_integer_arg(node: N):
        func_args = list[exp.Expr](node.expr.iter_expressions())

        if len(func_args) > 0 and isinstance(func_args[0], exp.Literal) and func_args[0].is_number:
            return node
        return None

    hooks = [Hook(name="only_integer_arg", kind=FunctionNode, func=only_integer_arg)]
    h = holder(sql=sql, dialect=DIALECT, with_tables=True, hooks=hooks)

    assert h.paths == [
        ['literal["hello"]', "column[fruit.processed.name]"],
        ["literal[3]", "function[MAX]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 5
    assert len(h.edges) == 3
