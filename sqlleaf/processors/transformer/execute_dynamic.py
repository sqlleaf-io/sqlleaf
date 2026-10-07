import logging

from sqlleaf.models.query import ExecuteDynamicQuery
from sqlleaf.processors.transformer import base

logger = logging.getLogger("sqlleaf")


class ExecuteDynamicTransformer(base.BaseQueryTransformer):
    QUERY = ExecuteDynamicQuery
