import logging

from sqlglot import exp
from sqlglot.optimizer.simplify import simplify

from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import ForInQuery
from sqlleaf.processors.transformer import base
from sqlleaf.typing import E

logger = logging.getLogger("sqlleaf")


class ForInTransformer(base.BaseQueryTransformer):
    QUERY = ForInQuery

    def transform(self, statement: E) -> E:
        """
        Simplify range bounds (start, end, and step expressions) in a FOR ... IN loop statement.

        Example:
            FOR i IN (1 + 1)..(2 * 3) BY (1 + 1) -> FOR i IN 2..6 BY 2
        """
        if isinstance(statement, pgexp.PGForIn):
            for key in ("start", "end", "step"):
                child = statement.args.get(key)
                if isinstance(child, exp.Expr):
                    statement.set(key, simplify(child))

        return statement
