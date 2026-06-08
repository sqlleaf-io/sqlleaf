import os
import sys

from sqlleaf.objects.query_types import TableQuery, UnloadQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


DIALECT = "redshift"


def test__select_pivot_no_alias(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);
    CREATE TABLE target(john_total INT);

    INSERT INTO target
    SELECT * FROM (
      SELECT name, amount
      FROM source
    )
    PIVOT (
      SUM(amount)
      FOR name IN ('john')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.amount]", "column[_0.amount]", "function[SUM]", "pivot[]", "column[target.john_total]"]
    ]
    assert h.nodes_full == [
        "pivot[source= target=john statement=2]",
        "function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]",
        "column[name=amount table=_0 type=INT kind=derived_table]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=john_total table=target type=INT kind=table]",
    ]
    assert len(h.edges) == 4


def test__select_pivot_alias(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, age INT, amount INT);
    CREATE TABLE target(john_total INT, john_average DECIMAL(10,2), mary_total INT, mary_average DECIMAL(10,2));

    INSERT INTO target
    SELECT * FROM (
      SELECT name, age, amount
      FROM source
    )
    PIVOT (
      SUM(amount) as total,
      AVG(age) as average
      FOR name IN ('john', 'mary')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.amount]", "column[_0.amount]", "function[SUM]", "pivot[]", "column[target.john_total]"],
        ["column[source.amount]", "column[_0.amount]", "function[SUM]", "pivot[]", "column[target.mary_total]"],
        ["column[source.age]", "column[_0.age]", "function[AVG]", "pivot[]", "column[target.john_average]"],
        ["column[source.age]", "column[_0.age]", "function[AVG]", "pivot[]", "column[target.mary_average]"],
    ]
    assert h.nodes_full == [
        "pivot[source=total target=john_total statement=2]",
        "pivot[source=average target=john_average statement=2]",
        "pivot[source=total target=mary_total statement=2]",
        "pivot[source=average target=mary_average statement=2]",
        "function[AVG type=DOUBLE query_depth=0 query_width=0 statement=2 select=1 func_depth=0 func_arg=0]",
        "function[AVG type=DOUBLE query_depth=0 query_width=0 statement=2 select=3 func_depth=0 func_arg=0]",
        "function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]",
        "function[SUM type=BIGINT query_depth=0 query_width=0 statement=2 select=2 func_depth=0 func_arg=0]",
        "column[name=age table=_0 type=INT kind=derived_table]",
        "column[name=amount table=_0 type=INT kind=derived_table]",
        "column[name=age table=source type=INT kind=table]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=john_average table=target type=DECIMAL(10, 2) kind=table]",
        "column[name=john_total table=target type=INT kind=table]",
        "column[name=mary_average table=target type=DECIMAL(10, 2) kind=table]",
        "column[name=mary_total table=target type=INT kind=table]",
    ]
    assert len(h.edges) == 14


def test__unload(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);

    UNLOAD ('SELECT * FROM source')
    TO 's3://object-path/name-prefix'
    IAM_ROLE 'arn:aws:iam::0123456789012:role/MyRedshiftRole';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[name path=s3://object-path/name-prefix]"],
        ["column[source.amount]", "column[amount path=s3://object-path/name-prefix]"],
    ]
    assert h.nodes_full == [
        "column[amount type=INT kind=file format=UNKNOWN path=s3://object-path/name-prefix]",
        "column[name type=VARCHAR kind=file format=UNKNOWN path=s3://object-path/name-prefix]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=name table=source type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2
    assert isinstance(h.queries[1], UnloadQuery)


def test__view(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);

    CREATE VIEW my_view AS SELECT name, amount FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[my_view.name]"],
        ["column[source.amount]", "column[my_view.amount]"],
    ]
    assert h.nodes_full == [
        "column[name=amount table=my_view type=INT kind=view]",
        "column[name=name table=my_view type=VARCHAR kind=view]",
        "column[name=amount table=source type=INT kind=table]",
        "column[name=name table=source type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 2


# Not supported:
# - CREATE EXTERNAL PROTECTED VIEW
# Parser error:
# - CREATE EXTERNAL VIEW IF NOT EXISTS AS
def test__view_external(holder):
    sql = """
    CREATE EXTERNAL VIEW fruit.ext_view
    AS SELECT name, age FROM fruit.raw;
    """

    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[fruit.ext_view.name]"],
        ["column[fruit.raw.age]", "column[fruit.ext_view.age]"],
    ]
    assert "column[name=name table=ext_view schema=fruit type=VARCHAR kind=view subkind=external]" in h.nodes_full
    assert "column[name=age table=ext_view schema=fruit type=INT kind=view subkind=external]" in h.nodes_full

    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__table_external(holder):
    sql = """
    CREATE EXTERNAL TABLE fruit.ext (
        name VARCHAR,
        age INT
    )
    ROW FORMAT DELIMITED
    FIELDS TERMINATED BY '\t'
    STORED AS TEXTFILE
    LOCATION 's3://my-bucket/new/fruit/';
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[name path=s3://my-bucket/new/fruit/]", "column[fruit.ext.name]"],
        ["column[age path=s3://my-bucket/new/fruit/]", "column[fruit.ext.age]"],
    ]
    assert "column[name type=UNKNOWN kind=file format=TEXTFILE path=s3://my-bucket/new/fruit/]" in h.nodes_full
    assert "column[name=age table=ext schema=fruit type=INT kind=table subkind=external]" in h.nodes_full
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_unpivot(holder):
    sql = """
    CREATE TABLE source(john_total INT);
    CREATE TABLE target(name VARCHAR, amount INT);

    INSERT INTO target
    SELECT name, amount
    FROM source
    UNPIVOT (
      amount FOR name IN (john_total AS 'john')
    );
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ['literal["john"]', "unpivot[]", "column[target.name]"],
        ["column[source.john_total]", "unpivot[]", "column[target.amount]"],
    ]
    assert h.nodes_full == [
        "unpivot[source= target=name statement=2]",
        "unpivot[source=john_total target=amount statement=2]",
        'literal["john" type=VARCHAR query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]',
        "column[name=john_total table=source type=INT kind=table]",
        "column[name=amount table=target type=INT kind=table]",
        "column[name=name table=target type=VARCHAR kind=table]",
    ]
    assert len(h.edges) == 4


# TODO: -- Multiple output columns
#  UNPIVOT (
#   (amount, quantity)
#   FOR name IN (
#     (john_total, john_count) AS 'john',
#     (jane_total, jane_count) AS 'jane'
#   )
# );

# TODO: -- Multiple UNPIVOTs
#  UNPIVOT (amount FOR name IN (...))
#  UNPIVOT (rating FOR category IN (...));


def test__table_temporary(holder):
    sql = """
    CREATE TABLE #banana (name VARCHAR);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == []
    assert [TableQuery] == list(map(type, h.queries))
    assert h.queries[0].property == "temporary"


def test__ctas_temporary(holder):
    sql = """
    CREATE TABLE #banana AS SELECT name, age FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[#banana.name]"],
        ["column[fruit.raw.age]", "column[#banana.age]"],
    ]
    assert "column[name=age table=#banana type=INT kind=table subkind=temporary]" in h.nodes_full
    assert "column[name=name table=#banana type=VARCHAR kind=table subkind=temporary]" in h.nodes_full

    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__insert_with_cte(holder):
    sql = """
    INSERT INTO fruit.processed (name, age)
    (WITH cte AS (SELECT name, age FROM fruit.raw) SELECT * FROM cte ORDER BY 1 LIMIT 10);
    """
    h = holder(sql=sql, dialect=DIALECT, with_tables=True)

    assert h.paths == [
        ["column[fruit.raw.name]", "column[cte.name]", "column[fruit.processed.name]"],
        ["column[fruit.raw.age]", "column[cte.age]", "column[fruit.processed.age]"],
    ]
    assert len(h.nodes) == 6
    assert len(h.edges) == 4


def test__exclude(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, kind VARCHAR, age INT);
    CREATE TABLE target (name VARCHAR, kind VARCHAR);

    INSERT INTO target
    SELECT * EXCLUDE age FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [["column[source.name]", "column[target.name]"], ["column[source.kind]", "column[target.kind]"]]
    assert len(h.nodes) == 4
    assert len(h.edges) == 2


def test__select_into(holder):
    sql = """
    CREATE TABLE source (name VARCHAR, age INT);
    CREATE TABLE target (name VARCHAR, age INT);

    SELECT name, age INTO target FROM source;
    SELECT name, age INTO TEMPORARY other FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[source.name]", "column[other.name]"],
        ["column[source.name]", "column[target.name]"],
        ["column[source.age]", "column[other.age]"],
        ["column[source.age]", "column[target.age]"],
    ]
    assert "column[name=age table=source type=INT kind=table]" in h.nodes_full
    assert "column[name=age table=other type=INT kind=table subkind=temporary]" in h.nodes_full
    assert len(h.nodes) == 6
    assert len(h.edges) == 4
