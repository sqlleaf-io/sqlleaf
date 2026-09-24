from __future__ import annotations

import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.models.query.user_defined_function import _extract_function_info, FunctionParam
from sqlleaf.typing import TargetInfo


@dataclass(frozen=True)
class ProcedureQueryProperties:
    schema_name: t.Optional[str]
    procedure_name: str
    signature: str
    language: t.Optional[str]
    column_defs: t.List[exp.ColumnDef]
    parameters: t.List[FunctionParam]
    args: t.List[dict]
    inner_statements: t.List[exp.Expr]

    @classmethod
    def from_expression(cls, expr: exp.Create, object_mapping: mappings.ObjectMapping) -> ProcedureQueryProperties:
        table = util.get_table(expr)
        schema_name = table.db
        procedure_name = table.name

        # Full signature as string (e.g., etl.my_proc(v_session_id VARCHAR))
        signature = str(expr.this)

        language = util.get_language_property(expr)
        _, _, parameters = _extract_function_info(expr)

        args = [{"name": p.name, "type": str(p.type)} for p in parameters]
        column_defs: t.List[exp.ColumnDef] = expr.this.expressions

        body_expr = expr.expression
        inner_statements: t.List[exp.Expr] = []
        if body_expr:
            inner_statements = util.iter_inner_statements(body_expr, object_mapping.dialect, wrap=True, language=language)
            inner_statements = [
                stmt
                for stmt in inner_statements
                if not isinstance(stmt, (exp.EndStatement, exp.Column, exp.Identifier))
            ]

        return cls(
            schema_name=schema_name,
            procedure_name=procedure_name,
            signature=signature,
            language=language,
            column_defs=column_defs,
            parameters=parameters,
            args=args,
            inner_statements=inner_statements,
        )


class ProcedureQuery(Query):
    """
    Holds metadata related to stored procedures.
    """

    KIND = "procedure"

    def __init__(
        self,
        expr: exp.Create,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        table = util.get_table(expr)
        target_type = self._determine_expression_type(table, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=None,
            target_info=TargetInfo(expression=table, type=target_type),
        )
        self.properties = ProcedureQueryProperties.from_expression(expr, object_mapping)
        self.column_defs = self.properties.column_defs

    @property
    def schema(self) -> t.Optional[str]:
        return self.properties.schema_name

    @property
    def procedure(self) -> str:
        return self.properties.procedure_name

    @property
    def signature(self) -> str:
        return self.properties.signature

    @property
    def parameters(self):
        return self.properties.parameters

    @property
    def args(self) -> t.List[dict]:
        return self.properties.args

    @property
    def inner_statements(self) -> t.List[exp.Expr]:
        return self.properties.inner_statements

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "signature": self.signature,
            "args": self.args,
        }

    @property
    def name(self):
        return ".".join([var for var in [self.schema, self.procedure] if var])
