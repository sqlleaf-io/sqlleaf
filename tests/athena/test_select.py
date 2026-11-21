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
        [
            "column[awsdatacatalog.dbname.iceberg_table$files.record_count]",
            "column[awsdatacatalog.default.target.r_count]",
        ],
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

    assert h.paths == [
        ["column[awsdatacatalog.dbname.iceberg_table$manifests.path]", "column[awsdatacatalog.default.target.path]"]
    ]


def test__select_iceberg_metadata_field_history(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (snapshot_id bigint);
    INSERT INTO target (snapshot_id) SELECT snapshot_id FROM "dbname"."iceberg_table$history";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[awsdatacatalog.dbname.iceberg_table$history.snapshot_id]",
            "column[awsdatacatalog.default.target.snapshot_id]",
        ]
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
        [
            "column[awsdatacatalog.dbname.iceberg_table$partitions.record_count]",
            "column[awsdatacatalog.default.target.record_count]",
        ]
    ]


def test__select_iceberg_metadata_field_snapshots(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (operation varchar);
    INSERT INTO target (operation) SELECT operation FROM "dbname"."iceberg_table$snapshots";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[awsdatacatalog.dbname.iceberg_table$snapshots.operation]",
            "column[awsdatacatalog.default.target.operation]",
        ]
    ]


def test__select_iceberg_metadata_field_refs(holder):
    sql = """
    CREATE TABLE "dbname"."iceberg_table" (id bigint, data string, category string)
    TBLPROPERTIES ( 'table_type' = 'ICEBERG' );
    CREATE TABLE target (name varchar);
    INSERT INTO target (name) SELECT name FROM "dbname"."iceberg_table$refs";
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.dbname.iceberg_table$refs.name]", "column[awsdatacatalog.default.target.name]"]
    ]


def test__select_transform_lambda(holder):
    sql = """
    CREATE TABLE target (doubled ARRAY(INTEGER));
    INSERT INTO target (doubled)
    SELECT TRANSFORM(numbers, x -> x * 2) AS doubled
    FROM (VALUES (ARRAY[1, 2, 3])) AS t(numbers);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[2]", "function[MUL]", "function[TRANSFORM]", "column[awsdatacatalog.default.target.doubled]"],
        [
            "literal[{1,2,3}]",
            "column[t.numbers]",
            "function[TRANSFORM]",
            "column[awsdatacatalog.default.target.doubled]",
        ],
    ]
    assert len(h.edges) == 5


def test__select_unnest_with_ordinality(holder):
    sql = """
    CREATE TABLE my_table (tags ARRAY(VARCHAR));
    CREATE TABLE target (item VARCHAR, idx BIGINT);
    INSERT INTO target (item, idx)
    SELECT item, idx FROM my_table CROSS JOIN UNNEST(tags) WITH ORDINALITY AS t(item, idx);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[awsdatacatalog.default.my_table.tags]",
            "function[UNNEST]",
            "column[t.item]",
            "column[awsdatacatalog.default.target.item]",
        ],
        ["series[]", "column[t.idx]", "column[awsdatacatalog.default.target.idx]"],
    ]
    assert len(h.edges) == 5


def test__select_any_match_lambda(holder):
    sql = """
    CREATE TABLE students (scores ARRAY(INTEGER));
    CREATE TABLE target (passed BOOLEAN);
    INSERT INTO target (passed)
    SELECT ANY_MATCH(scores, x -> x >= 90) AS passed FROM students;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[awsdatacatalog.default.students.scores]",
            "function[ANY_MATCH]",
            "column[awsdatacatalog.default.target.passed]",
        ],
        [
            "literal[90]",
            "function[GTE]",
            "function[ANY_MATCH]",
            "column[awsdatacatalog.default.target.passed]",
        ],
    ]
    assert len(h.edges) == 4


def test__select_tablesample_system(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, kind VARCHAR);
    CREATE TABLE target (name VARCHAR, kind VARCHAR);
    INSERT INTO target (name, kind) SELECT * FROM source TABLESAMPLE SYSTEM (1);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.default.source.name]", "column[awsdatacatalog.default.target.name]"],
        ["column[awsdatacatalog.default.source.kind]", "column[awsdatacatalog.default.target.kind]"],
    ]
    assert len(h.edges) == 2


def test__select_array_sort_lambda(holder):
    sql = """
    CREATE TABLE source (name ARRAY(VARCHAR));
    CREATE TABLE target (name ARRAY(VARCHAR));
    INSERT INTO target (name)
    SELECT ARRAY_SORT(
      name,
      (x, y) -> CASE WHEN LENGTH(x) < LENGTH(y) THEN 1 WHEN LENGTH(x) > LENGTH(y) THEN -1 ELSE 0 END
    ) AS name FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            "column[awsdatacatalog.default.source.name]",
            "function[ARRAY_SORT]",
            "column[awsdatacatalog.default.target.name]",
        ],
        ["literal[0]", "function[ARRAY_SORT]", "column[awsdatacatalog.default.target.name]"],
        ["literal[1]", "function[ARRAY_SORT]", "column[awsdatacatalog.default.target.name]"],
        ["literal[-1]", "function[ARRAY_SORT]", "column[awsdatacatalog.default.target.name]"],
    ]
    assert len(h.edges) == 5


def test__select_last_value_ignore_nulls(holder):
    sql = """
    CREATE TABLE source (ts TIMESTAMP, age INT);
    CREATE TABLE target (ts TIMESTAMP, age INT);
    INSERT INTO target (ts, age)
    SELECT ts, LAST_VALUE(age) IGNORE NULLS OVER (ORDER BY ts) AS age FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.default.source.ts]", "column[awsdatacatalog.default.target.ts]"],
        [
            "column[awsdatacatalog.default.source.age]",
            "window[LAST_VALUE]",
            "column[awsdatacatalog.default.target.age]",
        ],
    ]
    assert len(h.edges) == 3


def test__select_unnest_sequence_dates(holder):
    sql = """
    CREATE TABLE target (calendar_day DATE);
    INSERT INTO target (calendar_day)
    SELECT d AS calendar_day FROM UNNEST(SEQUENCE(DATE '2026-11-01', DATE '2026-11-21', INTERVAL '1' DAY)) AS t(d);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        [
            'literal["2026-11-01"]',
            "function[CAST]",
            "series[]",
            "function[UNNEST]",
            "column[t.d]",
            "column[awsdatacatalog.default.target.calendar_day]",
        ],
        [
            'literal["2026-11-21"]',
            "function[CAST]",
            "series[]",
            "function[UNNEST]",
            "column[t.d]",
            "column[awsdatacatalog.default.target.calendar_day]",
        ],
        [
            'interval["1 DAY"]',
            "series[]",
            "function[UNNEST]",
            "column[t.d]",
            "column[awsdatacatalog.default.target.calendar_day]",
        ],
    ]
    assert len(h.edges) == 8


def test__select_extract_timezone_hour(holder):
    sql = """
    CREATE TABLE target (tz INTEGER);
    INSERT INTO target (tz) SELECT EXTRACT(TIMEZONE_HOUR FROM TIMESTAMP '2020-05-10 12:34:56 +08:35') AS tz;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["var[TIMEZONE_HOUR]", "function[EXTRACT]", "column[awsdatacatalog.default.target.tz]"],
        [
            'literal["2020-05-10 12:34:56 +08:35"]',
            "function[CAST]",
            "function[EXTRACT]",
            "column[awsdatacatalog.default.target.tz]",
        ],
    ]
    assert len(h.edges) == 4


def test__select_concat_ws(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, kind VARCHAR);
    CREATE TABLE target (name VARCHAR);
    INSERT INTO target (name) SELECT CONCAT_WS('-', name, kind) AS name FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["-"]', "function[CONCAT_WS]", "column[awsdatacatalog.default.target.name]"],
        [
            "column[awsdatacatalog.default.source.name]",
            "function[CONCAT_WS]",
            "column[awsdatacatalog.default.target.name]",
        ],
        [
            "column[awsdatacatalog.default.source.kind]",
            "function[CONCAT_WS]",
            "column[awsdatacatalog.default.target.name]",
        ],
    ]
    assert len(h.edges) == 4


def test__select_array_agg_groups_window(holder):
    sql = """
    CREATE TABLE target (arr ARRAY(INTEGER));
    INSERT INTO target (arr)
    SELECT array_agg(a) OVER(ORDER BY a ASC NULLS FIRST GROUPS BETWEEN 1 PRECEDING AND 2 FOLLOWING) AS arr
    FROM (VALUES 3, 3, 2, null) T(a);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["literal[3]", "column[t.a]", "window[ARRAY_AGG]", "column[awsdatacatalog.default.target.arr]"],
        ["literal[3]", "column[t.a]", "window[ARRAY_AGG]", "column[awsdatacatalog.default.target.arr]"],
        ["literal[2]", "column[t.a]", "window[ARRAY_AGG]", "column[awsdatacatalog.default.target.arr]"],
        ["null[NULL]", "column[t.a]", "window[ARRAY_AGG]", "column[awsdatacatalog.default.target.arr]"],
    ]
    assert len(h.edges) == 6


def test__select_lag_window(holder):
    sql = """
    CREATE TABLE source (age INTEGER);
    CREATE TABLE target (age INTEGER);
    INSERT INTO target (age) SELECT LAG(age) OVER (ORDER BY age) AS age FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.default.source.age]", "window[LAG]", "column[awsdatacatalog.default.target.age]"],
    ]
    assert len(h.edges) == 2


def test__select_rank_window(holder):
    sql = """
    CREATE TABLE source (name VARCHAR);
    CREATE TABLE target (r BIGINT);
    INSERT INTO target (r) SELECT RANK() OVER (ORDER BY name) AS r FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["window[RANK]", "column[awsdatacatalog.default.target.r]"]]
    assert len(h.edges) == 1


# TODO: MATCH_RECOGNIZE()
