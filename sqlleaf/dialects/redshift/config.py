from sqlglot.dialects.redshift import Redshift

from sqlleaf.dialects.base import DialectConfig


class RedshiftConfig(DialectConfig):
    DIALECT = "redshift"
    DEFAULT_PROCEDURE_LANGUAGE = "PLPGSQL"


# Redshift supports 'SELECT ... INTO', so keep it as a SELECT rather than rewriting it to 'CREATE TABLE AS'
Redshift.Generator.SUPPORTS_SELECT_INTO = True
