import logging
import typing as t
from sqlglot import exp
from sqlleaf.processors.transformer import base, udf
from sqlleaf.models.query import ExecuteQuery

logger = logging.getLogger("sqlleaf")

class ExecuteTransformer(base.BaseQueryTransformer):
    def transform(self) -> exp.Expr:
        query: ExecuteQuery = self.query

        execute_name = query.name
        execute_args = query.arguments

        logger.debug(f"Replacing EXECUTE query for plan '{execute_name}'")

        replacement_exprs = udf.substitute_execute_with_plan(execute_name, execute_args, query.object_mapping)

        if not replacement_exprs:
            return self.statement

        return replacement_exprs[0]
