import typing as t

from sqlleaf.models.query.base import Query as Query
from sqlleaf.models.query.copy import CopyQuery as CopyQuery
from sqlleaf.models.query.ctas import CTASQuery as CTASQuery
from sqlleaf.models.query.database import DatabaseQuery as DatabaseQuery
from sqlleaf.models.query.delete import DeleteQuery as DeleteQuery
from sqlleaf.models.query.holder import QueryHolder as QueryHolder
from sqlleaf.models.query.insert import InsertQuery as InsertQuery
from sqlleaf.models.query.merge import MergeQuery as MergeQuery
from sqlleaf.models.query.procedure import ProcedureQuery as ProcedureQuery
from sqlleaf.models.query.put import PutQuery as PutQuery
from sqlleaf.models.query.schema import SchemaQuery as SchemaQuery
from sqlleaf.models.query.select import SelectQuery as SelectQuery
from sqlleaf.models.query.sequence import SequenceQuery as SequenceQuery
from sqlleaf.models.query.stage import StageQuery as StageQuery
from sqlleaf.models.query.table import TableQuery as TableQuery
from sqlleaf.models.query.trigger import TriggerQuery as TriggerQuery
from sqlleaf.models.query.type import TypeQuery as TypeQuery
from sqlleaf.models.query.unload import UnloadQuery as UnloadQuery
from sqlleaf.models.query.update import UpdateQuery as UpdateQuery
from sqlleaf.models.query.user_defined_function import FunctionParam as FunctionParam
from sqlleaf.models.query.user_defined_function import UserDefinedFunctionQuery as UserDefinedFunctionQuery
from sqlleaf.models.query.view import ViewQuery as ViewQuery

Q = t.TypeVar("Q", bound=Query)
