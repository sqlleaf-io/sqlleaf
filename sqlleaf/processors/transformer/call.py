import logging

from sqlleaf.models.query import CallQuery
from sqlleaf.processors.transformer import base

logger = logging.getLogger("sqlleaf")


class CallTransformer(base.BaseQueryTransformer):
    QUERY = CallQuery
