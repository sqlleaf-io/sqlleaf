import typing as t

from sqlglot import exp

from sqlleaf.settings.base import BaseDialectSettings


class AthenaSettings(BaseDialectSettings):
    DIALECT = "athena"
    PSEUDOCOLUMNS = {
        "$bucket": "BIGINT",
        "$file_modified_time": "TIMESTAMP",
        "$file_size": "BIGINT",
        "$partition": "VARCHAR",
        "$path": "VARCHAR",
    }

    @property
    def system_columns(self) -> t.List[exp.ColumnDef]:
        return [
            exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(kind, self.DIALECT))
            for name, kind in self.PSEUDOCOLUMNS.items()
        ]
