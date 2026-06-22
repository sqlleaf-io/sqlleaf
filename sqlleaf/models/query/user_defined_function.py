from __future__ import annotations

import typing as t
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query
from sqlleaf.typing import TargetInfo


class UserDefinedFunctionQuery(Query):
    KIND = "udf"

    def __init__(
        self,
        expr: exp.Create,
        dialect,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):
        source = None
        target = expr.this.this

        target_type = self._determine_expression_type(target, dialect)

        super().__init__(
            dialect=dialect,
            statement=expr,
            statement_index=statement_index,
            object_mapping=object_mapping,
            source_info=source,
            target_info=TargetInfo(expression=target, type=target_type),
        )

        self.collect()


    @property
    def name(self):
        return ".".join([var for var in [self.schema_name, self.function_name] if var])

    def collect(self) -> None:
        """
        Collect the required information from the function DDL into class attributes.
        """
        function_name, schema_name, parameters = _extract_function_info(self.statement)
        return_type, return_columns = _extract_return_info(self.statement, parameters, self.object_mapping)

        # Filter parameters to only include those that can be passed as input
        input_parameters = [p for p in parameters if p.is_input or p.is_variadic]

        language = _extract_language(self.statement)

        body_expr = self.statement.args.get("expression")
        inner_statements = []

        if body_expr:
            # Determine the function body and all internal expressions.
            # If the body is a string literal or heredoc (common in PostgreSQL), parse it to extract
            # individual statements. Otherwise, use the expression itself.
            if isinstance(body_expr, (exp.Literal, exp.Heredoc)):
                body_text = body_expr.this.strip()
                try:
                    inner_statements = sqlglot.parse(body_text, dialect="postgres")
                except Exception:
                    pass
            elif isinstance(body_expr, exp.Return):
                inner_statements = [exp.select(body_expr.this)]
            else:
                inner_statements = [exp.select(body_expr)]

        self.schema_name: str = schema_name
        self.function_name: str = function_name
        self.return_type: exp.DataType = return_type
        self.language: str = language
        self.parameters: t.List[FunctionParam] = input_parameters
        self.return_columns: t.List[exp.ColumnDef] = return_columns
        self.inner_statements: t.List[exp.Expr] = inner_statements

        self.column_defs = return_columns


def get_user_defined_data_type(kind: t.Optional[str | exp.Identifier | exp.Dot] = None) -> exp.DataType:
    if kind:
        if isinstance(kind, str):
            if "." in kind:
                parts = kind.split(".")
                kind = exp.Dot.build([exp.Identifier(this=p, quoted=False) for p in parts])
            else:
                kind = exp.Identifier(this=kind, quoted=False)
        return exp.DataType.build(kind, udt=True, dialect="postgres")
    return exp.DataType.build("USER-DEFINED", dialect="postgres")


@dataclass
class FunctionParam:
    """A parameter of a user-defined function."""

    name: str
    type: exp.DataType
    default: t.Optional[exp.Expression] = None
    is_input: bool = True
    is_output: bool = False
    is_variadic: bool = False


def _extract_function_info(expression: exp.Create) -> t.Tuple[str, t.Optional[str], t.List[FunctionParam]]:
    """Extracts the name, schema, and parameters from a CREATE FUNCTION expression."""
    target = expression.this
    parameters = []

    # Process the function definition which includes name and parameters
    if isinstance(target, exp.UserDefinedFunction):
        function_expr = target.this
        # Iterate through column definitions to find parameters
        for i, col_def in enumerate(target.expressions):
            if isinstance(col_def, exp.ColumnDef):
                param_name = col_def.this.name
                param_type = col_def.kind
                param_default = None
                is_input = True
                is_output = False
                is_variadic = False

                # Determine the parameter types (IN, OUT, etc)
                constraints = col_def.args.get("constraints")
                if constraints:
                    for constraint in constraints:
                        kind = constraint.args.get("kind")
                        if isinstance(kind, exp.DefaultColumnConstraint):
                            param_default = kind.this
                        elif isinstance(constraint, exp.InOutColumnConstraint):
                            is_input = constraint.args.get("input_")
                            is_output = constraint.args.get("output")
                            is_variadic = constraint.args.get("variadic")

                # Unnamed parameter logic inside ColumnDef (e.g., VARIADIC numeric[])
                if param_name.upper() == "VARIADIC":
                    is_variadic = True
                    param_name = f"${i + 1}"
                    # The type might be stored in a way that includes the rest of the definition
                    # In Postgres unnamed VARIADIC, sqlglot might parse it such that 'variadic' is the name
                    # and the type is numeric[]

                # Handle special keywords used as parameter names by assigning positional placeholders
                if param_name.upper() in ("IN", "OUT", "INOUT"):
                    if param_name.upper() == "OUT":
                        is_input = False
                        is_output = True
                    elif param_name.upper() == "INOUT":
                        is_input = True
                        is_output = True
                    param_name = f"${i + 1}"
                parameters.append(
                    FunctionParam(
                        name=param_name,
                        type=param_type,
                        default=param_default,
                        is_input=is_input,
                        is_output=is_output,
                        is_variadic=is_variadic,
                    )
                )
            elif _is_unnamed_parameter(col_def):
                # Handle unnamed parameters like CREATE FUNCTION hello(TEXT) or (VARIADIC numeric[])
                param_name = f"${i + 1}"
                is_variadic = False

                type_node = col_def
                if isinstance(col_def, exp.UserDefinedFunction):
                    is_variadic = col_def.sql().upper().startswith("variadic")
                    type_node = col_def.this

                type_sql = type_node.this.lower()

                if type_sql in ("anyelement", "anyarray"):
                    param_type = get_user_defined_data_type(kind=type_sql)
                else:
                    try:
                        param_type = exp.DataType.build(type_node.this, dialect="postgres")
                    except Exception:
                        # e.g. for tables as parameters - CREATE FUNCTION hello(people), where 'people' is a table
                        param_type = get_user_defined_data_type(kind=type_node.this)

                parameters.append(FunctionParam(name=param_name, type=param_type, is_variadic=is_variadic))
    else:
        function_expr = target.this

    # Determine function name and schema from the table-like expression structure
    if isinstance(function_expr, exp.Table):
        name = function_expr.name
        schema = function_expr.args.get("db").this if function_expr.args.get("db") else None
    else:
        name = function_expr.sql()
        schema = None

    return name, schema, parameters


def _is_unnamed_parameter(col_def: exp.ColumnDef) -> bool:
    return isinstance(col_def, exp.Identifier) or (
        isinstance(col_def, exp.UserDefinedFunction) and isinstance(col_def.this, exp.Identifier)
    )


def _extract_return_info(
    expression: exp.Create, parameters: t.List[FunctionParam], object_mapping: mappings.ObjectMapping
) -> t.Tuple[t.Optional[exp.DataType], t.List[exp.ColumnDef]]:
    """Extracts return type and return columns from a CREATE FUNCTION expression."""
    return_type = None
    return_columns = []

    # Check for OUT/INOUT parameters that determine the return structure
    out_params: t.List[FunctionParam] = [p for p in parameters if p.is_output]

    if out_params:
        if len(out_params) == 1:
            return_type = out_params[0].type
        else:
            return_type = get_user_defined_data_type()
            for param in out_params:
                col_name = param.name
                if col_name.startswith("$"):
                    col_name = f"column{col_name[1:]}"
                return_columns.append(exp.ColumnDef(this=exp.to_identifier(col_name), kind=param.type))

    # Loop through properties to find the RETURNS clause
    for prop in expression.args.get("properties", {}).expressions:
        if isinstance(prop, exp.ReturnsProperty):
            if prop.this is None:
                continue

            # Check if it's a RETURNS TABLE(...) with multiple columns
            if isinstance(prop.this, exp.Schema):
                return_type = get_user_defined_data_type()
                # Extract individual column definitions for table-returning functions
                for col_def in prop.this.expressions:
                    if isinstance(col_def, exp.ColumnDef):
                        return_columns.append(col_def)
            else:
                # Standard return type (e.g., RETURNS TEXT, RETURNS person, RETURNS TABLE_NAME)
                return_type_sql = prop.this.sql().lower()
                return_type = prop.this

                if return_type_sql == "void":
                    return_type = exp.DataType.build("NULL")
                else:
                    target_table = exp.to_table(return_type_sql)
                    found_query = object_mapping.lookup_type_query(target_table, raise_on_missing=False)
                    if not found_query:
                        found_query = object_mapping.lookup_table_query(target_table, raise_on_missing=False)

                    if found_query:
                        return_columns = found_query.get_column_defs()

    return return_type, return_columns


def _extract_language(expression: exp.Create) -> t.Optional[str]:
    """Extracts the language from a CREATE FUNCTION expression."""
    for prop in expression.args.get("properties", {}).expressions:
        if isinstance(prop, exp.LanguageProperty):
            return prop.this.sql().lower()
    return None
