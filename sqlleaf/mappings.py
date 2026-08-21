from __future__ import annotations

import typing as t

from sqlglot import MappingSchema, exp
from sqlglot.dialects.dialect import DialectType
from sqlglot.schema import nested_set
from sqlglot.trie import new_trie

from sqlleaf import exception, util
from sqlleaf.models.query import (
    CTASQuery,
    DatabaseQuery,
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

ColumnMapping = t.Union[t.Dict, str, t.List]


class ObjectMapping(MappingSchema):
    """
    Extends sqlglot.MappingSchema to provide additional functionality related to tracking exp.Table

    Specifically, we need to track the exp.Table inside the exp.Create statements, as they contain more information
    than the exp.Table that we encounter later when parsing INSERT statements.
    """

    def __init__(self, dialect: str):
        """
        Initialize a mapping of tables parts to exp.Table
        """
        super().__init__(
            dialect=dialect, normalize=False
        )  # Set `normalize=False` to prevent an unnecessary second parse.
        self.kind_mapping = {}
        self.kind_mapping_trie = {}
        self.session_variables: dict[str, exp.Expr] = {}

    def add_database_query(self, query: DatabaseQuery) -> None:
        self._add_query(kind="database", query=query, dialect=query.dialect)

    def add_prepare_query(self, query: PrepareQuery) -> None:
        self._add_query(kind="prepare", query=query, dialect=query.dialect)

    def add_procedure_query(self, query: ProcedureQuery) -> None:
        self._add_query(kind="procedure", query=query, dialect=query.dialect)

    def add_schema_query(self, query: SchemaQuery) -> None:
        self._add_query(kind="schema", query=query, dialect=query.dialect)

    def add_sequence_query(self, query: SequenceQuery) -> None:
        self._add_query(kind="sequence", query=query, dialect=query.dialect)

    def add_stage_query(self, query: StageQuery) -> None:
        self._add_query(kind="stage", query=query, dialect=query.dialect)

    def add_table_query(
        self, query: TableQuery | ViewQuery | CTASQuery, column_mapping: t.Optional[ColumnMapping] = None
    ) -> None:
        self._add_query(kind="table", query=query, column_mapping=column_mapping, dialect=query.dialect)

    def add_trigger_query(self, query: TriggerQuery) -> None:
        self._add_query(kind="trigger", query=query, dialect=query.dialect)

    def add_type_query(self, query: TypeQuery) -> None:
        self._add_query(kind="type", query=query, dialect=query.dialect)

    def add_udf_query(self, query: UserDefinedFunctionQuery, column_mapping: t.Optional[ColumnMapping] = None) -> None:
        self._add_query(kind="udf", query=query, column_mapping=column_mapping, dialect=query.dialect)

    def _add_query(
        self,
        kind: str,
        query: Q,
        column_mapping: t.Optional[ColumnMapping] = None,
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        match_depth: bool = False,
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
        column_mapping: t.Optional[ColumnMapping] = None,
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        match_depth: bool = False,
    ):
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
    ):
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

    def lookup_procedure_query(self, table: exp.Table, raise_on_missing: bool = True) -> ProcedureQuery | None:
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
    ) -> t.List[UserDefinedFunctionQuery] | None:
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
                raise exception.MappingError(f"Could not find '{object.this}' of type '{kind}' in mapping.")
            return None

        parts = self.table_parts(object)[0: len(self.supported_table_args)]
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
    def supported_table_args(self) -> t.Tuple[str, ...]:
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
            child_object_query = self.lookup_stage_query(table=table_expr, raise_on_missing=raise_on_missing)
        else:
            child_object_query = self.lookup_table_query(table=table_expr, raise_on_missing=raise_on_missing)

        if not child_object_query and raise_on_missing:
            raise exception.MappingError(message=f"Unknown table: {str(table_expr)}")

        return child_object_query

    def lookup_udf_call(
        self,
        node: exp.Anonymous,
    ) -> t.Optional[UserDefinedFunctionQuery]:
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


def resolve_overloaded_function(
    node: exp.Anonymous, candidates: t.List[UserDefinedFunctionQuery]
) -> t.Optional[UserDefinedFunctionQuery]:
    """
    Resolves the best function candidate for an overloaded function call.
    Applies some precedence rules (e.g., type matching, or non-variadic > variadic) but many are currently
    excluded due to the complexity of the rules.
    """
    if len(candidates) == 1:
        return candidates[0]

    # Function overloading: find the best match based on arguments
    args = node.expressions
    matches = []
    for candidate in candidates:
        if match_function_arguments(args, candidate):
            matches.append(candidate)

    if not matches:
        raise exception.MappingError(f"No matching function signatures found for args: {args}")

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


def match_function_arguments(args: t.List[exp.Expr], candidate: UserDefinedFunctionQuery) -> bool:
    """
    Checks if the provided arguments match the function candidate's parameters.
    Handles exact types, polymorphic types (anyelement, anyarray), and VARIADIC parameters.
    """
    params = candidate.parameters
    arg_count = len(args)
    param_count = len(params)

    has_variadic = any(p.is_variadic for p in params)

    if not has_variadic:
        if arg_count != param_count:
            return False

        for i, arg in enumerate(args):
            if not match_type(arg, params[i].type):
                return False
        return True

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

