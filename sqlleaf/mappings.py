from __future__ import annotations

import logging
import typing as t

from sqlglot import MappingSchema, exp
from sqlglot.dialects.dialect import DialectType
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.schema import nested_set
from sqlglot.trie import new_trie

from sqlleaf import exception, util
from sqlleaf.models.query import (
    CallQuery,
    CTASQuery,
    DatabaseQuery,
    FunctionParam,
    PrepareQuery,
    ProcedureQuery,
    Q,
    SchemaQuery,
    SequenceQuery,
    StageQuery,
    TableQuery,
    TriggerQuery,
    TypeQuery,
    UserDefinedFunctionQuery,
    ViewQuery,
)

ColumnMapping = t.Union[dict, str, list]
FunctionCallable = ProcedureQuery | UserDefinedFunctionQuery

logger = logging.getLogger("sqlleaf")


class ObjectMapping(MappingSchema):
    """
    Contains all the objects that get created, such as tables, procedures, functions, and sequences.

    We extends sqlglot.MappingSchema to provide additional functionality related to tracking these objects,
    while still allowing optimizer inside sqlglot to work (as it needs a mapping of objects to perform functions
    like qualification and simplification).
    """

    def __init__(self, dialect: str):
        super().__init__(
            dialect=dialect, normalize=False
        )  # Set `normalize=False` to prevent an unnecessary second parse.
        self.kind_mapping = {}
        self.kind_mapping_trie = {}
        # Session/global variables (e.g., SET var = ...)
        self.session_variables: dict[str, exp.Expr] = {}
        # Block-scoped variables: one dict per active block, innermost scope at the end
        self.variable_scopes: list[dict[str, exp.Expr]] = []

    # ---- Variable scope API ----
    def push_variable_scope(self) -> None:
        """Enter a new block scope."""
        self.variable_scopes.append({})

    def pop_variable_scope(self) -> None:
        """Leave the current block scope."""
        if self.variable_scopes:
            self.variable_scopes.pop()

    def declare_variable(self, name: str, value: exp.Expr | None = None) -> None:
        """Declare a variable in the current (innermost) scope."""
        val = value if value is not None else exp.Null()
        self.variable_scopes[-1][name] = val
        logger.debug(f"Declared variable: {name} := {val.sql(dialect=self.dialect)}")

    def set_variable(self, name: str, value: exp.Expr) -> None:
        """Assign a variable in the nearest scope where it was declared."""
        for scope in reversed(self.variable_scopes):
            if name in scope:
                scope[name] = value
                logger.debug(f"Set variable value: {name} := {value.sql(dialect=self.dialect)}")
                return

        raise exception.MappingError(f'"{name}" is not a known variable')

    def get_variable(self, name: str, raise_on_missing: bool = True) -> exp.Expr | None:
        """Resolve a variable by searching from innermost to outermost scopes."""
        for scope in reversed(self.variable_scopes):
            if name in scope:
                return scope[name]
        if raise_on_missing:
            raise exception.MappingError(f"Could not find value for variable: {name}")
        return None

    def get_variables_for(self, expressions: list[exp.Expr]) -> list[exp.Expr]:
        """
        Given a list of expressions as keys, fetch their values from the variable scope if they exist.

        Example:
            expressions = [ Literal[42], Column[name] ]
            variable scope = { Column[name] -> Literal['john'] }
            ->
            [ Literal['john'] ]
        """
        resolved = []
        for expr in expressions:
            if isinstance(expr, exp.Column) and not expr.table:
                variable = self.get_variable(expr.name, raise_on_missing=False)
                if variable is not None:
                    resolved.append(variable.copy())
                    continue
            resolved.append(expr)
        return resolved

    def get_scope(self) -> dict[str, exp.Expr]:
        """Return the current scope dict (innermost)."""
        return self.variable_scopes[-1]

    def add_database_query(self, query: DatabaseQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_prepare_query(self, query: PrepareQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_procedure_query(self, query: ProcedureQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_schema_query(self, query: SchemaQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_sequence_query(self, query: SequenceQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_stage_query(self, query: StageQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_table_query(
        self, query: TableQuery | ViewQuery | CTASQuery, column_mapping: ColumnMapping | None = None
    ) -> None:
        self._add_query(query=query, column_mapping=column_mapping, dialect=query.dialect, kind="table")

    def add_trigger_query(self, query: TriggerQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_type_query(self, query: TypeQuery) -> None:
        self._add_query(query=query, dialect=query.dialect)

    def add_udf_query(self, query: UserDefinedFunctionQuery, column_mapping: ColumnMapping | None = None) -> None:
        self._add_query(query=query, column_mapping=column_mapping, dialect=query.dialect)

    def _add_query(
        self,
        query: Q,
        column_mapping: ColumnMapping | None = None,
        dialect: DialectType = None,
        normalize: bool | None = None,
        match_depth: bool = False,
        kind: str = "",
    ) -> None:
        """
        Register or update a table. Updates are only performed if a new column mapping is provided.
        The added table must have the necessary number of qualifiers in its path to match the schema's nesting level.

        Args:
            kind: the expression's kind
            query: the query to store
            column_mapping: a column mapping that describes the structure of the table.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.
            match_depth: whether to enforce that the table must match the schema's depth or not.
        """
        # Initialize the structures. These are required by sqlglot.
        if not kind:
            kind = query.kind

        if kind not in self.kind_mapping:
            self.kind_mapping[kind] = {}
            self.kind_mapping_trie[kind] = new_trie({})

        # Normalize the table parts (catalog.db.table.column)
        table = query.get_target_as_table()
        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)
        parts = self.table_parts(normalized_table)

        if kind == "udf":
            # Store the UDF with other UDFs of the same name
            udfs_with_same_name = self.lookup_udf_query(table, raise_on_missing=False) or []
            query = [query] + udfs_with_same_name
        elif kind == "procedure":
            # Store the procedure with other overloads of the same name, replacing an identical signature
            procedures_with_same_name = self.lookup_procedure_query(table, raise_on_missing=False) or []
            other_overloads = [p for p in procedures_with_same_name if not _has_same_parameter_types(p, query)]
            query = [query] + other_overloads

        # Store the object
        nested_set(self.kind_mapping[kind], tuple(reversed(parts)), query)
        new_trie([parts], self.kind_mapping_trie[kind])

        if kind in ["table", "udf"] and column_mapping is not None:
            # Track the table's columns. UDFs are supported by sqlglot when qualifying columns
            # TODO: there is a bug here where multiple UDFs with the same name that have different return columns
            #  will have their column names overwritten (non-merged)
            self._add_columns_for_table(
                table=table,
                column_mapping=column_mapping,
                dialect=dialect,
                normalize=normalize,
                match_depth=match_depth,
            )

    def _add_columns_for_table(
        self,
        table: exp.Table,
        column_mapping: ColumnMapping | None = None,
        dialect: DialectType = None,
        normalize: bool | None = None,
        match_depth: bool = False,
    ) -> None:
        super().add_table(
            table=table,
            column_mapping=column_mapping,
            dialect=dialect,
            normalize=normalize,
            match_depth=match_depth,
        )

    def find_columns_for_table(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
        ensure_data_types: bool = False,
    ) -> None:
        """
        A nicer name for the parent's function.
        """
        return super().find(
            table,
            raise_on_missing=raise_on_missing,
            ensure_data_types=ensure_data_types,
        )

    def lookup_prepare_query(self, table: exp.Table, raise_on_missing: bool = True) -> PrepareQuery | None:
        return self._lookup_query(kind="prepare", object=table, raise_on_missing=raise_on_missing)

    def lookup_procedure_query(self, table: exp.Table, raise_on_missing: bool = True) -> list[ProcedureQuery] | None:
        # A procedure can be overloaded with different parameters, thus we return a list
        return self._lookup_query(kind="procedure", object=table, raise_on_missing=raise_on_missing)

    def lookup_sequence_query(self, table: exp.Table, raise_on_missing: bool = True) -> SequenceQuery | None:
        return self._lookup_query(kind="sequence", object=table, raise_on_missing=raise_on_missing)

    def lookup_stage_query(self, table: exp.Table, raise_on_missing: bool = True) -> StageQuery | None:
        return self._lookup_query(kind="stage", object=table, raise_on_missing=raise_on_missing)

    def lookup_table_query(self, table: exp.Table, raise_on_missing: bool = True) -> TableQuery | None:
        return self._lookup_query(kind="table", object=table, raise_on_missing=raise_on_missing)

    def lookup_trigger_query(self, table: exp.Table, raise_on_missing: bool = True) -> TriggerQuery | None:
        return self._lookup_query(kind="trigger", object=table, raise_on_missing=raise_on_missing)

    def lookup_type_query(self, table: exp.Table, raise_on_missing: bool = True) -> TypeQuery | None:
        return self._lookup_query(kind="type", object=table, raise_on_missing=raise_on_missing)

    def lookup_udf_query(
        self, table: exp.Table, raise_on_missing: bool = True
    ) -> list[UserDefinedFunctionQuery] | None:
        # A UDF can have multiple names but different types, thus we return a list
        return self._lookup_query(kind="udf", object=table, raise_on_missing=raise_on_missing)

    def _lookup_query(
        self,
        kind: str,
        object: exp.Table,
        raise_on_missing: bool,
    ) -> Q | None:
        """
        Returns the Query for a given object kind and exp.Table.

        This is different from the MappingSchema's find(), which returns the column mappings.
        This returns an exp.Table.

        Args:
            kind: the expression's kind
            object: the target object.
            raise_on_missing: whether to raise in case the schema is not found.

        Returns:
            The schema of the target object.
        """
        if kind not in self.kind_mapping:
            if raise_on_missing:
                if kind == "prepare":
                    knd = "PREPARE"
                else:
                    knd = "CREATE " + {"udf": "FUNCTION"}.get(kind, kind).upper()

                raise exception.MappingError(
                    f"Could not find '{object.this}' of type '{kind}' in mapping. Did you forget to define a '{knd}' statement?"
                )
            return None

        parts = self.table_parts(object)[0 : len(self.supported_table_args)]
        resolved_parts = self._find_in_trie(parts, self.kind_mapping_trie[kind], raise_on_missing)

        if resolved_parts is None:
            return None

        result = self.nested_get(resolved_parts, self.kind_mapping[kind], raise_on_missing=raise_on_missing)
        if not result:
            return None
        elif isinstance(result, dict):
            # The mapping object has varying depth if some objects use a catalog and others don't
            if object.name in result:
                return result[object.name]
            else:
                return None
        else:
            # Must be a Query
            return result

    # Override sqlglot's property. It seems to be buggy when using different dict sizes (catalog, schema, etc)
    @property
    def supported_table_args(self) -> tuple[str, ...]:
        return exp.TABLE_PARTS

    def get_table_or_stage(
        self, table: exp.Table | exp.Var, raise_on_missing: bool = True
    ) -> TableQuery | StageQuery | None:
        """
        Get the 'CREATE' query for a table or stage.
        """
        table_expr = table
        if isinstance(table_expr, exp.Var):
            table_expr = exp.Table(this=table)

        if str(table_expr).startswith("@"):
            child_object_query = self.lookup_stage_query(table=table_expr, raise_on_missing=False)
        else:
            child_object_query = self.lookup_table_query(table=table_expr, raise_on_missing=raise_on_missing)

        if not child_object_query and raise_on_missing:
            raise exception.MappingError(message=f"Unknown table: {str(table_expr)}")

        return child_object_query

    def lookup_udf_call(
        self,
        node: exp.Anonymous,
    ) -> UserDefinedFunctionQuery | None:
        """
        Looks up the UDF definition for a single exp.Anonymous node.
        Returns the matched UDF definition, or None if not found.
        """
        function_schema, function_name = util.get_udf_name(node)
        udf_object = exp.table_(table=function_name, db=function_schema)
        candidates = self.lookup_udf_query(table=udf_object, raise_on_missing=False)
        if not candidates:
            return None

        return resolve_overloaded_function(node, candidates)

    def lookup_procedure_call(self, node: CallQuery) -> ProcedureQuery | None:
        """
        Looks up the procedure definition for a CALL statement.
        Returns the matched procedure definition, or None if no procedure with that name exists.
        """
        procedure_table = exp.table_(table=node.procedure, db=node.schema)
        candidates = self.lookup_procedure_query(table=procedure_table, raise_on_missing=False)
        if not candidates:
            return None

        # Annotate copies so the call's own expressions are left untouched
        args = [arg.copy() for arg in node.args]
        for arg in args:
            annotate_types(_get_call_arg_value(arg), dialect=self.dialect, schema=self)

        return resolve_overloaded_procedure(args, candidates)


def resolve_overloaded_function(
    node: exp.Anonymous, candidates: list[UserDefinedFunctionQuery]
) -> UserDefinedFunctionQuery | None:
    """
    Resolves the best function candidate for an overloaded function call.
    Applies some precedence rules (e.g., type matching, or non-variadic > variadic) but many are currently
    excluded due to the complexity of the rules.
    """
    if len(candidates) == 1:
        return candidates[0]

    # Function overloading: find the best match based on arguments
    args = node.expressions
    matches = match_overloads(args, candidates, lambda a, c: match_callable_arguments(a, c.parameters), "function")

    if len(matches) == 1:
        return matches[0]

    # Preference rule: non-variadic is preferred over variadic
    non_variadic_matches = [m for m in matches if not any(p.is_variadic for p in m.parameters)]
    if non_variadic_matches:
        # Prefer more specific non-variadic matches over polymorphic ones
        specific_matches = [
            m
            for m in non_variadic_matches
            if not any(str(p.type).lower() in ("anyelement", "anyarray") for p in m.parameters)
        ]
        if specific_matches:
            return specific_matches[0]

        # If we only have polymorphic matches, prefer anyarray for array arguments
        if all(arg.type and arg.type.is_type(exp.DataType.Type.ARRAY) for arg in args):
            anyarray_matches = [
                m for m in non_variadic_matches if any(str(p.type).lower() == "anyarray" for p in m.parameters)
            ]
            if anyarray_matches:
                return anyarray_matches[0]

        return non_variadic_matches[0]

    return matches[0]


def _has_same_parameter_types(left: ProcedureQuery, right: ProcedureQuery) -> bool:
    """
    Compare the parameter types of two procedures.
    """
    return [str(p.type) for p in left.parameters] == [str(p.type) for p in right.parameters]


def match_overloads(
    args: list[exp.Expr],
    candidates: list[FunctionCallable],
    matcher: t.Callable[[list[exp.Expr], FunctionCallable], bool],
    kind: str,
) -> list[FunctionCallable]:
    """
    Returns the candidates whose signature matches the arguments.
    Raises if no candidate matches.
    """
    matches = [candidate for candidate in candidates if matcher(args, candidate)]
    if not matches:
        raise exception.MappingError(f"No matching {kind} signatures found for args: {args}")

    return matches


def resolve_overloaded_procedure(args: list[exp.Expr], candidates: list[ProcedureQuery]) -> ProcedureQuery:
    """
    Resolves the procedure overload that the CALL arguments bind to.
    Raises if no overload matches.

    Example:
        args = [annotate_types(exp.Literal.number(42))]  # type INT
        candidates = [p_text_proc, p_int_proc]
        # p_text_proc: ProcedureQuery for process_order(a TEXT)
        # p_int_proc:  ProcedureQuery for process_order(a INT)
        resolve_overloaded_procedure(args, candidates)
        -> p_int_proc  # process_order(a INT), even though the TEXT candidate is listed first
    """
    matches = match_overloads(args, candidates, lambda a, c: match_callable_arguments(a, c.parameters), "procedure")
    return matches[0]


def _get_call_arg_value(arg: exp.Expr) -> exp.Expr:
    """Returns the value of a CALL argument, unwrapping named notation (`name => value`)."""
    if isinstance(arg, exp.Kwarg):
        return arg.expression
    if isinstance(arg, exp.PropertyEQ):
        return arg.right
    return arg


def match_callable_arguments(args: list[exp.Expr], params: list[FunctionParam]) -> bool:
    """
    Checks if the call arguments bind to the parameters of a UDF or procedure.
    Positional arguments bind in order, named arguments bind by name, and any unbound parameter must have a default.
    A trailing variadic parameter absorbs the remaining positional arguments.
    Bound input parameters are type-checked, while OUT parameters and NULL arguments match any type.
    """
    positional = [arg for arg in args if not isinstance(arg, (exp.Kwarg, exp.PropertyEQ))]
    named = [arg for arg in args if isinstance(arg, (exp.Kwarg, exp.PropertyEQ))]

    has_variadic = bool(params) and params[-1].is_variadic
    fixed_count = len(params) - 1 if has_variadic else len(params)
    absorbed = [_get_call_arg_value(arg) for arg in positional[fixed_count:]]
    if absorbed and not has_variadic:
        return False

    bound = {i: _get_call_arg_value(arg) for i, arg in enumerate(positional[:fixed_count])}
    taken = set(bound)
    if absorbed:
        taken.add(fixed_count)

    for arg in named:
        arg_key = arg.this if isinstance(arg, exp.Kwarg) else arg.left
        index = next((i for i, p in enumerate(params) if p.name.lower() == arg_key.name.lower()), None)
        if index is None or index in taken:
            return False
        taken.add(index)
        bound[index] = _get_call_arg_value(arg)

    for i, param in enumerate(params):
        if absorbed and i == fixed_count:
            if not _match_variadic_arguments(absorbed, param.type):
                return False
        elif i not in bound:
            if param.default is None and not param.is_variadic:
                return False
        elif param.is_input and not isinstance(bound[i], exp.Null):
            if not _match_argument(bound[i], param.type):
                return False

    return True


def _match_argument(value: exp.Expr, target_type: exp.DataType) -> bool:
    # Mirror match_type's VARCHAR -> TEXT normalization, which is only applied to the argument side
    if target_type.is_type(exp.DataType.Type.VARCHAR):
        target_type = exp.DataType.build("TEXT")
    return match_type(value, target_type)


def _match_variadic_arguments(values: list[exp.Expr], array_type: exp.DataType) -> bool:
    """
    Checks the arguments absorbed by a variadic parameter. A single array argument (`VARIADIC arr`) is matched
    against the whole array type, otherwise each argument is matched against the array's element type.

    Example:
        # Each INT value matches the element type of INT[]
        values = [annotate_types(exp.Literal.number(1)), annotate_types(exp.Literal.number(2))]
        _match_variadic_arguments(values, exp.DataType.build("INT[]"))
        -> True
        # A string (VARCHAR) does not match INT
        values_fail = [annotate_types(exp.Literal.string("a"))]
        _match_variadic_arguments(values_fail, exp.DataType.build("INT[]"))
        -> False
    """
    if len(values) == 1 and values[0].type and values[0].type.is_type(exp.DataType.Type.ARRAY):
        return _match_argument(values[0], array_type)

    element_type = array_type.expressions[0] if array_type.is_type(exp.DataType.Type.ARRAY) else array_type
    return all(isinstance(value, exp.Null) or _match_argument(value, element_type) for value in values)


def match_type(arg: exp.Expr, target_type: exp.DataType) -> bool:
    """Matches an argument expression to a target data type."""
    arg_type = arg.type
    if not arg_type:
        # If type isn't annotated, we can't be sure, but let's try to be lenient or rely on annotate_types
        return True

    if arg_type.this == exp.DataType.Type.VARCHAR:
        arg_type = exp.DataType.build("TEXT")

    target_type_name = target_type.sql().lower()

    if target_type_name == "anyelement":
        return True
    if target_type_name == "anyarray":
        return arg_type.is_type(exp.DataType.Type.ARRAY)

    # If target is DECIMAL but arg is TEXT, they don't match
    if target_type.is_type(exp.DataType.Type.DECIMAL) and arg_type.is_type(exp.DataType.Type.TEXT):
        return False

    # Handle numeric type matching - Postgres allows implicit cast from literal to numeric
    if target_type.is_type(exp.DataType.Type.DECIMAL):
        if arg_type.is_type(exp.DataType.Type.DOUBLE, exp.DataType.Type.FLOAT, exp.DataType.Type.DECIMAL):
            return True
        # Literals often come as DOUBLE but should match NUMERIC
        if isinstance(arg, (exp.Literal, exp.Cast)):
            return True

    return exp.DataType.is_type(arg_type, target_type)
