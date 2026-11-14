from sqlglot.dialects.mysql import MySQL

from sqlleaf.dialects.base import DialectConfig, with_parameter_modes


class MySQLConfig(DialectConfig):
    DIALECT = "mysql"
    DEFAULT_PROCEDURE_LANGUAGE = "SQL"


# Monkeypatch sqlglot's MySQL parser so that MySQL procedure parameters also accept parameter modes
MySQL.Parser._parse_function_parameter = with_parameter_modes(MySQL.Parser._parse_function_parameter)

# MySQL supports 'SELECT ... INTO @var', so keep it as a SELECT rather than rewriting it to 'CREATE TABLE AS'
MySQL.Generator.SUPPORTS_SELECT_INTO = True
