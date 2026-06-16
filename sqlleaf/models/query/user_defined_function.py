from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import sqlglot
from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query.base import Query


class UserDefinedFunctionQuery(Query):
    def __init__(
        self,
        dialect,
        statement: exp.Create,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
    ):

        super().__init__(
            kind="udf",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            target_object=statement.this.this,
            object_mapping=object_mapping,
        )

        self.collect()

        # TODO: support 'default'
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in statement.this.find_all(exp.ColumnDef)
        ]

    @property
    def name(self):
        return ".".join([var for var in [self.schema_name, self.function_name] if var])

    def collect(self) -> None:
        """
        Collect the required information from the function DDL into class attributes.
        """
        function_name, schema_name, parameters = _extract_function_info(self.statement)
        return_type, return_columns, return_kind = _extract_return_info(self.statement)

        # If it's a composite type or table, look up the columns if not already found
        if return_type and not return_columns:
            # For lookup in get_types/get_tables, we still need the name of the type
            # But return_type is now an exp.DataType.Type.
            # We need to find the original type name from the expression.
            return_type_name = None
            for prop in self.statement.args.get("properties", {}).expressions:
                if isinstance(prop, exp.ReturnsProperty) and prop.this:
                    if not isinstance(prop.this, exp.Schema):
                        return_type_name = prop.this.sql().lower()
                    break

            if return_type_name:
                if return_kind == "custom":
                    return_columns = list(get_types()[return_type_name].keys())
                elif return_kind == "table":
                    return_columns = list(get_tables()[return_type_name].keys())

        # If no return columns from RETURNS TABLE, check for OUT/INOUT parameters
        if not return_columns:
            return_columns = [p.name for p in parameters if p.is_output]

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

        self.function_name = function_name
        self.return_type = return_type
        self.return_kind = return_kind
        self.language = language
        self.schema_name = schema_name
        self.parameters = input_parameters
        self.return_columns = return_columns
        self.inner_statements = inner_statements


def get_types() -> dict[str, dict[str, str]]:
    """
    CREATE TYPE person AS (name text, age int);
    """
    return {
        "person": {
            "name": "TEXT",
            "age": "INT",
        }
    }


def get_tables() -> dict[str, dict[str, str]]:
    """
    CREATE TABLE people (name TEXT, age INT);
    """
    return {
        "people": {
            "name": "TEXT",
            "age": "INT",
        }
    }


def get_user_defined_data_type() -> exp.DataType:
    return exp.DataType.build("USER-DEFINED", dialect="postgres")


@dataclass
class FunctionParam:
    """A parameter of a user-defined function."""

    name: str
    type: exp.DataType
    default: Optional[exp.Expression] = None
    is_input: bool = True
    is_output: bool = False
    is_variadic: bool = False


def _extract_function_info(expression: exp.Create) -> Tuple[str, Optional[str], List[FunctionParam]]:
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
                if param_name.lower() == "variadic":
                    is_variadic = True
                    param_name = f"${i + 1}"
                    # The type might be stored in a way that includes the rest of the definition
                    # In Postgres unnamed VARIADIC, sqlglot might parse it such that 'variadic' is the name
                    # and the type is numeric[]

                # Handle special keywords used as parameter names by assigning positional placeholders
                if param_name.upper() in ("IN", "OUT", "INOUT"):
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
                    is_variadic = col_def.sql().lower().startswith("variadic")
                    type_node = col_def.this

                type_sql = type_node.this.lower()

                if type_sql in ("anyelement", "anyarray"):
                    param_type = get_user_defined_data_type()
                    # We can't build it directly, but we can set its name
                    param_type.set("this", exp.Identifier(this=type_sql, quoted=False))
                else:
                    try:
                        param_type = exp.DataType.build(type_node.this, dialect="postgres")
                    except Exception:
                        # e.g. for tables as parameters - CREATE FUNCTION hello(people), where 'people' is a table
                        param_type = get_user_defined_data_type()

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


def _extract_return_info(expression: exp.Create) -> Tuple[Optional[exp.DataType], List[str], Optional[str]]:
    """Extracts return type, return columns, and return kind from a CREATE FUNCTION expression."""
    return_type = None
    return_columns = []
    return_kind = None

    # Loop through properties to find the RETURNS clause
    for prop in expression.args.get("properties", {}).expressions:
        if isinstance(prop, exp.ReturnsProperty):
            if prop.this is None:
                continue

            # Check if it's a RETURNS TABLE(...) with multiple columns
            if isinstance(prop.this, exp.Schema):
                return_type = get_user_defined_data_type()
                return_kind = "table"
                # Extract individual column names for table-returning functions
                for col_def in prop.this.expressions:
                    if isinstance(col_def, exp.ColumnDef):
                        return_columns.append(col_def.this.name)
            else:
                # Standard return type (e.g., RETURNS TEXT, RETURNS person, RETURNS TABLE_NAME)
                return_type_sql = prop.this.sql().lower()
                return_type = prop.this

                # TODO: get types/tables from UDFs
                if return_type_sql == "void":
                    return_kind = "void"
                    return_type = exp.DataType.build("NULL")
                elif return_type_sql in get_types():
                    return_kind = "custom"
                elif return_type_sql in get_tables():
                    return_kind = "table"
                else:
                    return_kind = "system"

    return return_type, return_columns, return_kind


def _extract_language(expression: exp.Create) -> Optional[str]:
    """Extracts the language from a CREATE FUNCTION expression."""
    for prop in expression.args.get("properties", {}).expressions:
        if isinstance(prop, exp.LanguageProperty):
            return prop.this.sql()
    return None
