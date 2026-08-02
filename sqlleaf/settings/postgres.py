import typing as t

from sqlglot import exp
from sqlglot.dialects import postgres

from sqlleaf.settings.base import BaseDialectSettings


class PostgresSettings(BaseDialectSettings):
    DIALECT = "postgres"
    PSEUDOCOLUMNS = {
        "cmax": "OID",
        "cmin": "OID",
        "ctid": "OID",
        "oid": "OID",
        "tableoid": "OID",
        "xmax": "OID",
        "xmin": "OID",
    }

    @property
    def system_columns(self) -> t.List[exp.ColumnDef]:
        return [
            exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(kind, self.DIALECT))
            for name, kind in self.PSEUDOCOLUMNS.items()
        ]

    @property
    def system_functions(self) -> t.Dict[str, t.List[str]]:
        """
        Map function names to their returned column names.
        """
        return {
            "aclexplode": ["grantor, grantee, privilege_type, is_grantable"],
            "json_array_elements": ["value"],
            "json_array_elements_text": ["value"],
            "json_each": ["key", "value"],
            "json_each_text": ["key", "value"],
            "jsonb_array_elements": ["value"],
            "jsonb_array_elements_text": ["value"],
            "jsonb_each": ["key", "value"],
            "jsonb_each_text": ["key", "value"],
            "ts_debug": ["alias, description, token, dictionaries, dictionary, lexemes"],
            "ts_parse": ["tokid", "token"],
            "ts_stat": ["word", "ndoc", "nentry"],
            "ts_token_type": ["tokid", "alias", "description"],
        }


# sqlglot is missing pseudocolumns for Postgres
postgres.Postgres.PSEUDOCOLUMNS = {c.upper() for c in PostgresSettings.PSEUDOCOLUMNS.keys()}
postgres.Postgres.EXCLUDES_PSEUDOCOLUMNS_FROM_STAR = True
