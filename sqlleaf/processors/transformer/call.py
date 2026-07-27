import logging
import typing as t
from sqlglot import exp
from sqlleaf.processors.transformer import base, substitute
from sqlleaf.models.query import CallQuery

logger = logging.getLogger("sqlleaf")

class CallTransformer(base.BaseQueryTransformer):
    def transform(self) -> exp.Expr:
        query: CallQuery = self.query

        procedure_table = exp.Table(
            this=exp.to_identifier(query.procedure),
            db=exp.to_identifier(query.schema) if query.schema else None,
        )
        matched_proc = query.object_mapping.lookup_procedure_query(procedure_table, raise_on_missing=False)
        if not matched_proc:
            return self.statement

        logger.debug(f"Replacing CALL query '{query.name}' with procedure body")

        param_map = {}
        positional_map = {}
        args = query.args

        for i, param in enumerate(matched_proc.parameters):
            arg_expr = substitute.find_arg(args, param, i) or param.default

            if arg_expr:
                param_map[param.name.lower()] = arg_expr
                positional_map[str(i + 1)] = arg_expr

        replacement_exprs = []
        for stmt in matched_proc.inner_statements:
            # Procedures can contain multiple statements
            replacement_exprs.append(substitute.substitute_parameters(stmt.copy(), None, param_map, positional_map))

        if not replacement_exprs:
            return self.statement

        # For now, we only care about the last statement for the canonical transformed state
        # (matching current behavior in transformer.py)
        return replacement_exprs[-1]
