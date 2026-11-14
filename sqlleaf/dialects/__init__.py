# Maps each dialect name to the module that registers its config or parser. Lazily imported for performance.
DIALECT_MODULES = {
    "athena": "sqlleaf.dialects.athena.config",
    "mysql": "sqlleaf.dialects.mysql.config",
    "plpgsql": "sqlleaf.dialects.plpgsql.p_dialect",
    "postgres": "sqlleaf.dialects.postgres.config",
}
