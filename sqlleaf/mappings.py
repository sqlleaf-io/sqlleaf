from __future__ import annotations

import typing as t

from sqlglot import MappingSchema, exp
from sqlglot.dialects.dialect import DialectType
from sqlglot.schema import nested_set
from sqlglot.trie import new_trie

from sqlleaf import exception
from sqlleaf.models.query import CTASQuery, Q, TypeQuery, ViewQuery

if t.TYPE_CHECKING:
    from sqlleaf.models.query import SequenceQuery, StageQuery, TableQuery, TriggerQuery, UserDefinedFunctionQuery

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
        table = query.get_target_as_table()

        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)
        parts = self.table_parts(normalized_table)

        if kind not in self.kind_mapping:
            self.kind_mapping[kind] = {}
            self.kind_mapping_trie[kind] = new_trie({})

        if kind == "udf":
            # Store the UDF with other UDFs of the same name
            udfs_with_same_name = self.lookup_udf_query(table, raise_on_missing=False) or []
            query = [query] + udfs_with_same_name

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

    def lookup_sequence_query(self, table: exp.Table, raise_on_missing: bool = True) -> SequenceQuery | None:
        return self._lookup_query(kind="sequence", table=table, raise_on_missing=raise_on_missing)

    def lookup_stage_query(self, table: exp.Table, raise_on_missing: bool = True) -> StageQuery | None:
        return self._lookup_query(kind="stage", table=table, raise_on_missing=raise_on_missing)

    def lookup_table_query(self, table: exp.Table, raise_on_missing: bool = True) -> TableQuery | None:
        return self._lookup_query(kind="table", table=table, raise_on_missing=raise_on_missing)

    def lookup_trigger_query(self, table: exp.Table, raise_on_missing: bool = True) -> TriggerQuery | None:
        return self._lookup_query(kind="trigger", table=table, raise_on_missing=raise_on_missing)

    def lookup_type_query(self, table: exp.Table, raise_on_missing: bool = True) -> TypeQuery | None:
        return self._lookup_query(kind="type", table=table, raise_on_missing=raise_on_missing)

    def lookup_udf_query(
        self, table: exp.Table, raise_on_missing: bool = True
    ) -> t.List[UserDefinedFunctionQuery] | None:
        # A UDF can have multiple names but different types, thus we return a list
        return self._lookup_query(kind="udf", table=table, raise_on_missing=raise_on_missing)

    def _lookup_query(
        self,
        kind: str,
        table: exp.Table,
        raise_on_missing: bool,
    ) -> Q | None:
        """
        Returns the Query for a given object kind and exp.Table.

        This is different from the MappingSchema's find(), which returns the column mappings.
        This returns an exp.Table.

        Args:
            kind: the expression's kind
            table: the target table.
            raise_on_missing: whether to raise in case the schema is not found.

        Returns:
            The schema of the target table.
        """
        if kind not in self.kind_mapping:
            return None

        parts = self.table_parts(table)[0 : len(self.supported_table_args)]
        resolved_parts = self._find_in_trie(parts, self.kind_mapping_trie[kind], raise_on_missing)

        if resolved_parts is None:
            return None

        result = self.nested_get(resolved_parts, self.kind_mapping[kind], raise_on_missing=raise_on_missing)
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

    def get_table_or_stage(self, table: exp.Table, raise_on_missing: bool = True) -> Q | None:
        """
        Get the 'CREATE' query for a table or stage.
        """
        if str(table).startswith("@"):
            child_object_query = self.lookup_stage_query(table=table)
        else:
            child_object_query = self.lookup_table_query(table=table)

        if not child_object_query and raise_on_missing:
            raise exception.SqlLeafException(message="Unknown table", table=str(table))

        return child_object_query
