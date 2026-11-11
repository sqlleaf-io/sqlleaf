from sqlglot import exp
from sqlglot.dialects import athena

from sqlleaf.dialects.base import BaseDialectSettings


class AthenaSettings(BaseDialectSettings):
    DIALECT = "athena"
    DEFAULT_USER_CATALOG = "awsdatacatalog"
    DEFAULT_SYSTEM_CATALOG = ""
    PSEUDOCOLUMNS = {
        "$bucket": "BIGINT",
        "$file_modified_time": "TIMESTAMP",
        "$file_size": "BIGINT",
        "$partition": "VARCHAR",
        "$path": "VARCHAR",
    }
    # Iceberg metadata fields
    METADATA_FIELDS = {
        "$files": {
            "content": "INTEGER",
            "file_path": "VARCHAR",
            "file_format": "VARCHAR",
            "record_count": "BIGINT",
            "file_size_in_bytes": "BIGINT",
            "column_sizes": "MAP(INTEGER, BIGINT)",
            "value_counts": "MAP(INTEGER, BIGINT)",
            "null_value_counts": "MAP(INTEGER, BIGINT)",
            "nan_value_counts": "MAP(INTEGER, BIGINT)",
            "lower_bounds": "MAP(INTEGER, VARCHAR)",
            "upper_bounds": "MAP(INTEGER, VARCHAR)",
            "key_metadata": "VARBINARY",
            "split_offsets": "ARRAY(BIGINT)",
            "equality_ids": "ARRAY(INTEGER)",
        },
        "$manifests": {
            "path": "VARCHAR",
            "length": "BIGINT",
            "partition_spec_id": "INTEGER",
            "added_snapshot_id": "BIGINT",
            "added_data_files_count": "INTEGER",
            "added_rows_count": "BIGINT",
            "existing_data_files_count": "INTEGER",
            "existing_rows_count": "BIGINT",
            "deleted_data_files_count": "INTEGER",
            "deleted_rows_count": "BIGINT",
            "partitions": "ARRAY(STRUCT(contains_null BOOLEAN, contains_nan BOOLEAN, lower_bound VARCHAR, upper_bound VARCHAR))",
        },
        "$history": {
            "made_current_at": "TIMESTAMP WITH TIME ZONE",
            "snapshot_id": "BIGINT",
            "parent_id": "BIGINT",
            "is_current_ancestor": "BOOLEAN",
        },
        "$partitions": {
            "partition": "STRUCT(category VARCHAR)",
            "record_count": "BIGINT",
            "file_count": "BIGINT",
            "total_size": "BIGINT",
            "data": "STRUCT(id STRUCT(min BIGINT, max BIGINT, null_count BIGINT, nan_count BIGINT), data STRUCT(min VARCHAR, max VARCHAR, null_count BIGINT, nan_count BIGINT))",
        },
        "$snapshots": {
            "committed_at": "TIMESTAMP WITH TIME ZONE",
            "snapshot_id": "BIGINT",
            "parent_id": "BIGINT",
            "operation": "VARCHAR",
            "manifest_list": "VARCHAR",
            "summary": "MAP(VARCHAR, VARCHAR)",
        },
        "$refs": {
            "name": "VARCHAR",
            "type": "VARCHAR",
            "snapshot_id": "BIGINT",
            "max_reference_age_in_ms": "BIGINT",
            "min_snapshots_to_keep": "INTEGER",
            "max_snapshot_age_in_ms": "BIGINT",
        },
    }

    @property
    def system_columns(self) -> list[exp.ColumnDef]:
        return [
            exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(kind, self.DIALECT))
            for name, kind in self.PSEUDOCOLUMNS.items()
        ]


# sqlglot is missing pseudocolumns for Athena
athena.Athena.PSEUDOCOLUMNS = {c.upper() for c in AthenaSettings.PSEUDOCOLUMNS.keys()}

# Prevents pseudocolumns from being included in 'SELECT *' expansions
athena.Athena.EXCLUDES_PSEUDOCOLUMNS_FROM_STAR = True
