import typing as t

from sqlleaf.models.node.base import EdgeAttributes as EdgeAttributes
from sqlleaf.models.node.base import GraphAttributes as GraphAttributes
from sqlleaf.models.node.base import NodeAttributes as NodeAttributes
from sqlleaf.models.node.column import ColumnNode as ColumnNode
from sqlleaf.models.node.column import FileColumnNode as FileColumnNode
from sqlleaf.models.node.column import StageColumnNode as StageColumnNode
from sqlleaf.models.node.dynamodb import DynamoDbNode as DynamoDbNode
from sqlleaf.models.node.function import FunctionNode as FunctionNode
from sqlleaf.models.node.interval import IntervalNode as IntervalNode
from sqlleaf.models.node.json import JsonPathNode as JsonPathNode
from sqlleaf.models.node.literal import LiteralNode as LiteralNode
from sqlleaf.models.node.null import NullNode as NullNode
from sqlleaf.models.node.pivot import PivotNode as PivotNode
from sqlleaf.models.node.pivot import UnpivotNode as UnpivotNode
from sqlleaf.models.node.program import ProgramNode as ProgramNode
from sqlleaf.models.node.sequence import SequenceNode as SequenceNode
from sqlleaf.models.node.star import StarNode as StarNode
from sqlleaf.models.node.stream import StreamNode as StreamNode
from sqlleaf.models.node.user_defined_function import UserDefinedFunctionNode as UserDefinedFunctionNode
from sqlleaf.models.node.var import VarNode as VarNode
from sqlleaf.models.node.variable import VariableNode as VariableNode
from sqlleaf.models.node.window import WindowNode as WindowNode

N = t.TypeVar("N", bound=NodeAttributes)
TargetNodeType = ColumnNode | DynamoDbNode | FileColumnNode | StageColumnNode | StreamNode | ProgramNode
