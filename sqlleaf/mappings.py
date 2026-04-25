import typing as t

from sqlglot import exp, MappingSchema
from sqlglot.dialects.dialect import DialectType
from sqlglot.schema import nested_set
from sqlglot.trie import new_trie

from sqlleaf.objects.query_types import TableQuery

ColumnMapping = t.Union[t.Dict, str, t.List]

from sqlleaf import exception


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
        self.kind_mapping = {}
        self.kind_mapping_trie = {}

    def add_query(
        self,
        kind: str,
        query,
        column_mapping: t.Optional[ColumnMapping] = None,
        dialect: DialectType = None,
        normalize: t.Optional[bool] = None,
        match_depth: bool = False,
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
        table = query.child_table
        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)
        parts = self.table_parts(normalized_table)

        if kind not in self.kind_mapping:
            self.kind_mapping[kind] = {}
            self.kind_mapping_trie[kind] = new_trie({})

        nested_set(self.kind_mapping[kind], tuple(reversed(parts)), query)
        new_trie([parts], self.kind_mapping_trie[kind])

        if kind == "table" and column_mapping is not None:
            # Track the table's columns
            self.add_columns_for_table(
                table=table,
                column_mapping=column_mapping,
                dialect=dialect,
                normalize=normalize,
                match_depth=match_depth,
            )

    def add_columns_for_table(
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

    def find_query(
        self,
        kind: str,
        table: exp.Table,
        raise_on_missing: bool = True,
    ) -> t.Optional[TableQuery]:
        """
        Returns the Query for a given object kind and exp.Table.

        This is different from the MappingSchema's find(), which returns the column mappings.
        This returns an exp.Table.

        Args:
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

    def get_table_or_stage(self, table: exp.Table, raise_on_missing: bool = True):
        """
        Get the 'CREATE' query for a table or stage.
        """
        if str(table).startswith("@"):
            child_table_query = self.find_query(kind="stage", table=table)
        else:
            child_table_query = self.find_query(kind="table", table=table)

        if not child_table_query and raise_on_missing:
            raise exception.SqlLeafException(message="Unknown table", table=str(table))

        return child_table_query
