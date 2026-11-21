import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "athena"


def test__select_pseudocolumns(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target (name) SELECT "$path" FROM source WHERE "$path" LIKE '%2023-01-01%';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[awsdatacatalog.default.source.$path]", "column[awsdatacatalog.default.target.name]"]]
    assert h.nodes_full == [
        "column[name=$path type=VARCHAR properties=[kind=table table=source schema=default catalog=awsdatacatalog]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 1


def test__cte_struct_one_column(holder):
    sql = """
    CREATE TABLE target (name struct<first:VARCHAR>);

    WITH dataset AS (
      SELECT CAST(ROW('Bob') AS ROW(first VARCHAR)) AS users
    )
    INSERT INTO target (name)
    SELECT dataset.users FROM dataset
    """
    # +--------------------+
    # | name               |
    # +--------------------+
    # | {FIRST=Bob}        |
    # +--------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            'literal["Bob"]',
            "function[ROW]",
            "function[CAST]",
            "column[dataset.users]",
            "column[awsdatacatalog.default.target.name]",
        ]
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        "function[name=CAST type=STRUCT<first VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "column[name=users type=STRUCT<first VARCHAR> properties=[kind=cte table=dataset statement=1]]",
        "column[name=name type=STRUCT<first VARCHAR> properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 4


def test__cte_struct_two_columns(holder):
    sql = """
    CREATE TABLE target (name struct<first:VARCHAR, last:VARCHAR>);

    WITH dataset AS (
      SELECT CAST(ROW('Bob', 'Smith') AS ROW(first VARCHAR, last VARCHAR)) AS users
    )
    INSERT INTO target (name)
    SELECT dataset.users FROM dataset
    """
    # +------------------------+
    # | name                   |
    # +------------------------+
    # | {FIRST=Bob,LAST=Smith} |
    # +------------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            'literal["Bob"]',
            "function[ROW]",
            "function[CAST]",
            "column[dataset.users]",
            "column[awsdatacatalog.default.target.name]",
        ],
        [
            'literal["Smith"]',
            "function[ROW]",
            "function[CAST]",
            "column[dataset.users]",
            "column[awsdatacatalog.default.target.name]",
        ],
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        'literal[name="Smith" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]',
        "function[name=CAST type=STRUCT<first VARCHAR, last VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR, VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "column[name=users type=STRUCT<first VARCHAR, last VARCHAR> properties=[kind=cte table=dataset statement=1]]",
        "column[name=name type=STRUCT<first VARCHAR, last VARCHAR> properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 5


def test__cte_with_row_complex(holder):
    sql = """
    CREATE TABLE target (first VARCHAR, last VARCHAR);

    WITH dataset AS (
      SELECT
        CAST(
          ROW('Bob', ROW('Smith')) AS ROW(first_name VARCHAR, other ROW(last_name VARCHAR))
        ) AS people
    )
    INSERT INTO target (first, last)
    SELECT people.first_name, people.other.last_name
    FROM dataset;
    """
    # +--------------------------------------------+
    # | people                                     |
    # +--------------------------------------------+
    # | {FIRST_NAME=Bob, OTHER={LAST_NAME=Smith}}  |
    # +--------------------------------------------+
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            'literal["Bob"]',
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[awsdatacatalog.default.target.first]",
        ],
        [
            'literal["Bob"]',
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[awsdatacatalog.default.target.last]",
        ],
        [
            'literal["Smith"]',
            "function[ROW]",
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[awsdatacatalog.default.target.first]",
        ],
        [
            'literal["Smith"]',
            "function[ROW]",
            "function[ROW]",
            "function[CAST]",
            "column[dataset.people]",
            "column[awsdatacatalog.default.target.last]",
        ],
    ]
    assert h.nodes_full == [
        'literal[name="Bob" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=0]]',
        'literal[name="Smith" type=VARCHAR position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=3 func_arg=1]]',
        "function[name=CAST type=STRUCT<first_name VARCHAR, other STRUCT<last_name VARCHAR>> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=0 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR, STRUCT<VARCHAR>> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=1 func_arg=0]]",
        "function[name=ROW type=STRUCT<VARCHAR> position=[query_depth=1 query_width=0 statement=1 select=0 func_depth=2 func_arg=1]]",
        "column[name=people type=STRUCT<first_name VARCHAR, other STRUCT<last_name VARCHAR>> properties=[kind=cte table=dataset statement=1]]",
        "column[name=first type=VARCHAR properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
        "column[name=last type=VARCHAR properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 7


def test__select_iceberg_metadata_field_files(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (f_path varchar, r_count bigint);
    INSERT INTO target (f_path, r_count) SELECT file_path, record_count FROM "dbname"."iceberg_table$files";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.dbname.iceberg_table$files.file_path]", "column[awsdatacatalog.default.target.f_path]"],
        ["column[awsdatacatalog.dbname.iceberg_table$files.record_count]", "column[awsdatacatalog.default.target.r_count]"],
    ]
    assert h.nodes_full == [
        "column[name=file_path type=VARCHAR properties=[kind=table table=iceberg_table schema=dbname catalog=awsdatacatalog metadata=$files]]",
        "column[name=record_count type=BIGINT properties=[kind=table table=iceberg_table schema=dbname catalog=awsdatacatalog metadata=$files]]",
        "column[name=f_path type=VARCHAR properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
        "column[name=r_count type=BIGINT properties=[kind=table table=target schema=default catalog=awsdatacatalog]]",
    ]


def test__select_iceberg_metadata_field_manifests(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (path varchar);
    INSERT INTO target (path) SELECT path FROM "dbname"."iceberg_table$manifests";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[awsdatacatalog.dbname.iceberg_table$manifests.path]", "column[awsdatacatalog.default.target.path]"]]


def test__select_iceberg_metadata_field_history(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (snapshot_id bigint);
    INSERT INTO target (snapshot_id) SELECT snapshot_id FROM "dbname"."iceberg_table$history";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.dbname.iceberg_table$history.snapshot_id]", "column[awsdatacatalog.default.target.snapshot_id]"]
    ]


def test__select_iceberg_metadata_field_partitions(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (record_count bigint);
    INSERT INTO target (record_count) SELECT record_count FROM "dbname"."iceberg_table$partitions";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.dbname.iceberg_table$partitions.record_count]", "column[awsdatacatalog.default.target.record_count]"]
    ]


def test__select_iceberg_metadata_field_snapshots(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (operation varchar);
    INSERT INTO target (operation) SELECT operation FROM "dbname"."iceberg_table$snapshots";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[awsdatacatalog.dbname.iceberg_table$snapshots.operation]", "column[awsdatacatalog.default.target.operation]"]]


def test__select_iceberg_metadata_field_refs(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (name varchar);
    INSERT INTO target (name) SELECT name FROM "dbname"."iceberg_table$refs";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[awsdatacatalog.dbname.iceberg_table$refs.name]", "column[awsdatacatalog.default.target.name]"]]
