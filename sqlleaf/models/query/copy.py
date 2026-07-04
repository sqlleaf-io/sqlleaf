from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import exception, mappings, util
from sqlleaf.models.query.base import Query
from sqlleaf.typing import SourceExprType, SourceInfo, TargetExprType, TargetInfo

logger = logging.getLogger("sqlleaf")


@dataclass(frozen=True)
class CopyQueryParameters:
    file_format: str = "TEXT"
    load_data: bool = True
    is_a_job: bool = False
    job_action: str = ""
    job_name: str = ""
    job_auto_run: bool = True

    @classmethod
    def from_expression(cls, expr: exp.Copy, source_info: SourceInfo, target_info: TargetInfo) -> CopyQueryParameters:
        """
        Extract the parameters of the COPY statement.

        For example,
            Input: "COPY FROM ... FORMAT AS CSV NOLOAD"
            Params: ["FORMAT AS CSV", "NOLOAD"]
        """
        params_dict: t.Dict[str, t.Any] = {}

        params_list = []
        # Filter for the parameters we need
        for param in expr.args.get("params", []):
            if isinstance(param, exp.CopyParameter) and isinstance(param.this, exp.Var):
                params_list.append(param)

        for i, param in enumerate(params_list):
            param_name = param.this.name.upper()
            if param_name == "FORMAT":
                params_dict["file_format"] = str(param.expression)
            elif param_name == "NOLOAD":
                params_dict["load_data"] = False
            elif param_name == "JOB":
                params_dict["is_a_job"] = True
                try:
                    # COPY <command> JOB CREATE <name>
                    job_command = params_list[i + 1].this.name.upper()
                    job_name = params_list[i + 1].expression.name
                    params_dict["job_action"] = job_command
                    params_dict["job_name"] = job_name
                except IndexError:
                    message = "Missing one or more parameters to follow expression 'COPY .. JOB'"
                    raise exception.SqlLeafException(message=message)
            elif param_name == "AUTO":
                # COPY <command> JOB CREATE <name> AUTO ON | OFF
                params_dict["job_auto_run"] = str(param.expression) == "ON"
        return cls(**params_dict)

    @property
    def is_active(self) -> bool:
        """
        An active COPY query is one that has lineage. It is either:
        - a regular COPY query
        - a JOB that is either 'RUN' or 'CREATE and AUTO=ON'
        """
        if not self.is_a_job and self.load_data:
            return True
        if self.job_action == "RUN":
            return True
        if self.job_auto_run and self.job_action == "CREATE":
            return True
        return False


class CopyQuery(Query):
    KIND = "copy"

    def __init__(self, expr: exp.Copy, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        source, target = self.get_source_and_target_expressions(expr, dialect)

        if dialect == "snowflake":
            util.rename_if_stage(source, target)

        source_type = self._determine_expression_type(source, dialect)
        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=SourceInfo(expression=source, type=source_type),
            target_info=TargetInfo(expression=target, type=target_type),
        )
        self.parameters = self.get_params()
        self.qualify_and_annotate()

    def get_params(
        self,
    ) -> CopyQueryParameters:
        return CopyQueryParameters.from_expression(self.statement, self.source_info, self.target_info)

    def is_query_active(self) -> bool:
        logger.debug(self.parameters)
        return self.parameters.is_active

    def get_source_and_target_expressions(
        self, expr: exp.Copy, dialect: str
    ) -> t.Tuple[SourceExprType, TargetExprType]:
        """
        Determine the source and target expressions of the query.
        """
        if dialect in ["postgres", "redshift"]:
            # Postgres treats STDOUT and STDIN the same

            if expr.args["kind"]:
                # COPY X FROM STDOUT/STDIN
                source = expr.args["files"][0]
                target = expr.args["this"]
                if isinstance(target, exp.Schema):
                    target = target.this
            else:
                # COPY X TO STDOUT/STDIN
                source = expr.args["this"]
                target = expr.args["files"][0]
                if isinstance(source, exp.Schema):
                    source = source.this

        elif dialect == "snowflake":
            source = expr.args["files"][0]
            target = expr.args["this"]

        # It may be a subquery
        source = source.unnest()
        target = target.unnest()

        return source, target
