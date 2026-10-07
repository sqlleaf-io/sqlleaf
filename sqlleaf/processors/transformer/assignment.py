import logging

from sqlleaf.models.query import AssignmentQuery
from sqlleaf.processors.transformer import base
from sqlleaf.typing import E

logger = logging.getLogger("sqlleaf")


class AssignmentTransformer(base.BaseQueryTransformer):
    QUERY = AssignmentQuery

    def postprocess(self, statement: E) -> E:
        if qry := statement.args.get("query"):
            super().postprocess(qry)
            # TODO: the transformer functions need to be stateless to prevent this weirdness
            return statement
        return super().postprocess(statement)
