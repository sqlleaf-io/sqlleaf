from dataclasses import dataclass


# @dataclass(frozen=True)
@dataclass()
class NodeContext:
    statement_index: int = 0
    select_index: int = 0
    function_depth: int = 0
    function_arg_index: int = 0
    node_depth: int = 0
