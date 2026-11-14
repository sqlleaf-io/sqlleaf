import typing as t

import sqlglot
from sqlglot import Dialect, exp


# Wrap a function parameter parser so that it also accepts IN, OUT, and INOUT parameter modes
def with_parameter_modes(parse_function_parameter: t.Callable) -> t.Callable:
    def _parse_function_parameter(self) -> exp.Expr | None:
        mode = self._match_texts(("INOUT", "IN", "OUT")) and self._prev.text.upper()
        parameter = parse_function_parameter(self)
        if mode and parameter:
            parameter.append(
                "constraints",
                exp.InOutColumnConstraint(input_=mode in ("IN", "INOUT"), output=mode in ("OUT", "INOUT")),
            )
        return parameter

    return _parse_function_parameter


class DialectConfig:
    # A registry to store subclasses
    _dialects = {}
    DIALECT = ""
    DEFAULT_USER_CATALOG = ""
    DEFAULT_SYSTEM_CATALOG = ""
    # The language of procedures that do not declare one explicitly
    DEFAULT_PROCEDURE_LANGUAGE: str | None = None
    # Metadata fields, keyed by their suffix (e.g. '$files' in 'my_table$files'), mapped to their column names and types
    METADATA_FIELDS: dict[str, dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        if cls.DIALECT:
            DialectConfig._dialects[cls.DIALECT] = cls

    def __new__(cls, dialect: str) -> DialectConfig:
        """Returns the config registered for the dialect name, or the base config if none is registered."""
        return super().__new__(DialectConfig._dialects.get(dialect, DialectConfig))

    @property
    def SYSTEM_COLUMNS(self) -> list[exp.ColumnDef]:
        """
        Represents system columns.
        """
        return []

    @property
    def SYSTEM_FUNCTIONS(self) -> dict[str, list[str]]:
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

    class ParameterModeDialect(Dialect):
        """
        The generic dialect, which also accepts IN, OUT, and INOUT parameter modes in procedure parameters.
        """

        class Parser(sqlglot.Parser):
            _parse_function_parameter = with_parameter_modes(sqlglot.Parser._parse_function_parameter)
