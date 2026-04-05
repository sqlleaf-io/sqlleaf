from dataclasses import dataclass


@dataclass(frozen=True)
class NodeContext:
    statement_index: str = ''
    select_index: int = 0
    function_depth: int = 0
    function_arg_index: int = 0
    node_depth: int = 0
