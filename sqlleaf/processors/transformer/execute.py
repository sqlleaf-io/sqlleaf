import logging

from sqlleaf.models.query import ExecuteQuery
from sqlleaf.processors.transformer import base

logger = logging.getLogger("sqlleaf")


class ExecuteTransformer(base.BaseQueryTransformer):
    QUERY = ExecuteQuery
