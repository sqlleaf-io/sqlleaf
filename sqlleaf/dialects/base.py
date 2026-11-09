from sqlglot import exp


class BaseDialectSettings:
    # A registry to store subclasses
    _dialects = {}
    DIALECT = ""
    DEFAULT_USER_CATALOG = ""
    DEFAULT_SYSTEM_CATALOG = ""
    # Metadata fields, keyed by their suffix (e.g. '$files' in 'my_table$files'), mapped to their column names and types
    METADATA_FIELDS: dict[str, dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        if cls.DIALECT:
            BaseDialectSettings._dialects[cls.DIALECT] = cls

    @classmethod
    def from_dialect(cls, dialect: str) -> BaseDialectSettings:
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(dialect)
        if not target_class:
            return BaseDialectSettings()
        return target_class()

    @property
    def system_columns(self) -> list[exp.ColumnDef]:
        """
        Represents system columns.
        """
        return []

    @property
    def system_functions(self) -> dict[str, list[str]]:
        """
        Represents system functions.
        """
        return {}

    def get_metadata_field(self, table_name: str) -> str | None:
        """
        Returns the metadata field of a table name (e.g. '$files' for 'my_table$files').
        """
        for suffix in self.METADATA_FIELDS:
            if table_name.lower().endswith(suffix):
                return suffix
        return None

    def get_metadata_field_column_defs(self, suffix: str) -> list[exp.ColumnDef]:
        """
        Returns the column definitions of the metadata table with the given field (e.g. '$files').
        """
        return [
            exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(kind, self.DIALECT))
            for name, kind in self.METADATA_FIELDS[suffix].items()
        ]
