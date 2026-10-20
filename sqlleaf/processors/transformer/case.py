from sqlleaf.models.query import CaseQuery
from sqlleaf.processors.transformer import base
from sqlleaf.typing import E


class CaseTransformer(base.BaseQueryTransformer):
    QUERY = CaseQuery

    def transform(self, statement: E) -> E:
        return statement
