import typing as t

from sqlglot import exp, MappingSchema
from sqlglot.dialects.dialect import DialectType
from sqlglot.schema import nested_set
from sqlglot.trie import new_trie

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
        super().__init__(dialect=dialect, normalize=False)  # Set `normalize=False` to prevent an unnecessary second parse.
        self.table_mapping = {}
        self.table_mapping_trie = new_trie({})

        self.sequence_mapping = {}
        self.sequence_mapping_trie = new_trie({})

        self.user_defined_function_mapping = {}
        self.user_defined_function_mapping_trie = new_trie({})

        self.trigger_mapping = {}
        self.trigger_mapping_trie = new_trie({})

        self.stored_procedure_mapping = {}
        self.stored_procedure_mapping_trie = new_trie({})

        self.stage_mapping = {}
        self.stage_mapping_trie = new_trie({})

    def add_table_mapping(
        self,
        query,  # structs.TableQuery
        column_mapping: t.Optional[ColumnMapping] = None,
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        match_depth: bool = True,
    ) -> None:
        """
        Register or update a table. Updates are only performed if a new column mapping is provided.
        The added table must have the necessary number of qualifiers in its path to match the schema's nesting level.

        Args:
            table: the `Table` expression instance or string representing the table.
            column_mapping: a column mapping that describes the structure of the table.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.
            match_depth: whether to enforce that the table must match the schema's depth or not.
        """
        self.add_column_mapping(
            table=query.child_table,
            column_mapping=column_mapping,
            dialect=dialect,
            normalize=normalize,
            match_depth=match_depth,
        )

        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.table_mapping, mapping_trie=self.table_mapping_trie)

    def add_column_mapping(
        self,
        table: exp.Table,
        column_mapping: t.Optional[ColumnMapping] = None,
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        match_depth: bool = True,
    ) -> None:
        """
        Add to the table and columns sqlglot MappingSchema for its internal methods.
        """
        super().add_table(
            table=table,
            column_mapping=column_mapping,
            dialect=dialect,
            normalize=normalize,
            match_depth=match_depth,
        )

    def add_sequence_mapping(
        self,
        query,  # structs.SequenceQuery
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
    ) -> None:
        """
        Track the exp.Table inside a "CREATE SEQUENCE ..." statement
        """
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.sequence_mapping, mapping_trie=self.sequence_mapping_trie)

    def add_user_defined_function_mapping(
        self,
        query,  # structs.UserDefinedFunctionQuery
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
    ) -> None:
        """
        Track the exp.Table inside a "CREATE FUNCTION ..." statement
        """
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.user_defined_function_mapping, mapping_trie=self.user_defined_function_mapping_trie)

    def add_trigger_mapping(
        self,
        query,  # structs.TriggerQuery
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
    ) -> None:
        """
        Track the exp.Table inside a "CREATE SEQUENCE ..." statement
        """
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.trigger_mapping, mapping_trie=self.trigger_mapping_trie)

    def add_stored_procedure_mapping(
        self,
        query,  # structs.ProcedureQuery
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
    ) -> None:
        """
        Track the exp.Table inside a "CREATE STORED PROCEDURE ..." statement
        """
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.stored_procedure_mapping, mapping_trie=self.stored_procedure_mapping_trie)

    def add_stage_mapping(
            self,
            query,  # structs.StageQuery
            dialect: DialectType = None,
            normalize: t.Optional[bool] = None,
    ) -> None:
        """
        Track the exp.Table inside a "CREATE STAGE ..." statement
        """
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.stage_mapping, mapping_trie=self.stage_mapping_trie)
        # Track it as a table so that we can resolve columns within COPY queries
        self._add_mapping(query, dialect=dialect, normalize=normalize, mapping=self.table_mapping, mapping_trie=self.table_mapping_trie)

    def _add_mapping(
        self,
        query,  # structs.Query
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        mapping: dict = None,
        mapping_trie: dict = None,
    ) -> None:
        table = query.child_table
        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)
        parts = self.table_parts(normalized_table)

        nested_set(mapping, tuple(reversed(parts)), query)
        new_trie([parts], mapping_trie)

    def find_columns(
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

    def find_table(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Returns the schema of a given table.

        This is different from the MappingSchema's find(), which returns the column mappings.
        This returns an exp.Table.

        Args:
            table: the target table.
            raise_on_missing: whether to raise in case the schema is not found.
            ensure_data_types: whether to convert `str` types to their `DataType` equivalents.

        Returns:
            The schema of the target table.
        """
        return self._find_in_mapping(table, self.table_mapping, self.table_mapping_trie, raise_on_missing)

    def find_sequence(
        self,
        sequence: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Identical to find_table()
        """
        return self._find_in_mapping(
            sequence,
            self.sequence_mapping,
            self.sequence_mapping_trie,
            raise_on_missing,
        )

    def find_user_defined_function(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Identical to find_table()
        """
        return self._find_in_mapping(
            table,
            self.user_defined_function_mapping,
            self.user_defined_function_mapping_trie,
            raise_on_missing,
        )

    def find_trigger(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Identical to find_table()
        """
        return self._find_in_mapping(table, self.trigger_mapping, self.trigger_mapping_trie, raise_on_missing)

    def find_stored_procedure(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Identical to find_table()
        """
        return self._find_in_mapping(
            table,
            self.stored_procedure_mapping,
            self.stored_procedure_mapping_trie,
            raise_on_missing,
        )

    def find_stage(
        self,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """
        Identical to find_table()
        """
        return self._find_in_mapping(
            table,
            self.stage_mapping,
            self.stage_mapping_trie,
            raise_on_missing,
        )

    def _find_in_mapping(
        self,
        table: exp.Table,
        mapping: t.Dict,
        trie: t.Dict,
        raise_on_missing: bool = True,
    ) -> t.Optional[t.Any]:
        """ """
        parts = self.table_parts(table)[0 : len(self.supported_table_args)]
        resolved_parts = self._find_in_trie(parts, trie, raise_on_missing)

        if resolved_parts is None:
            return None

        result = self.nested_get(resolved_parts, mapping, raise_on_missing=raise_on_missing)
        # print('Table:', parts, 'Resolved:', resolved_parts, 'Result:', result)
        if not result:
            return None
        elif isinstance(result, dict):
            # The mapping table has varying depth if some tables use a catalog and others don't
            if table.name in result:
                return result[table.name]
            else:
                return None
        else:
            # Must be exp.Table
            return result

    # Override sqlglot's property. It seems to be buggy when using different dict sizes (catalog, schema, etc)
    @property
    def supported_table_args(self) -> t.Tuple[str, ...]:
        return exp.TABLE_PARTS
