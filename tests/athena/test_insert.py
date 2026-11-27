import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "athena"


def test__insert_into_select(holder):
    sql = """
    CREATE TABLE fruit.raw (name VARCHAR, amount INT);
    CREATE TABLE fruit.processed (name VARCHAR, amount INT);

    INSERT INTO fruit.processed
    SELECT name, amount
    FROM fruit.raw;
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.paths == [
        ["column[awsdatacatalog.fruit.raw.name]", "column[awsdatacatalog.fruit.processed.name]"],
        ["column[awsdatacatalog.fruit.raw.amount]", "column[awsdatacatalog.fruit.processed.amount]"],
    ]
    assert h.nodes_full == [
        "column[name=amount type=INT properties=[kind=table table=processed schema=fruit catalog=awsdatacatalog]]",
        "column[name=name type=VARCHAR properties=[kind=table table=processed schema=fruit catalog=awsdatacatalog]]",
        "column[name=amount type=INT properties=[kind=table table=raw schema=fruit catalog=awsdatacatalog]]",
        "column[name=name type=VARCHAR properties=[kind=table table=raw schema=fruit catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 2


def test__insert_select_exclude_columns(holder):
    sql = """
    CREATE TABLE db.tbl (col1 VARCHAR, col2 VARCHAR, col3 VARCHAR);
    CREATE TABLE db.target (col3 VARCHAR);

    INSERT INTO db.target (col3)
    SELECT * FROM TABLE(exclude_columns(input => TABLE(db.tbl), columns => DESCRIPTOR(col1, col2)));
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert h.holders[2].transformed.statement.sql(dialect=DIALECT) == (
        "INSERT INTO awsdatacatalog.db.target (col3) SELECT tbl.col3 AS col3 FROM awsdatacatalog.db.tbl AS tbl"
    )
    assert h.paths == [["column[awsdatacatalog.db.tbl.col3]", "column[awsdatacatalog.db.target.col3]"]]
    assert h.nodes_full == [
        "column[name=col3 type=VARCHAR properties=[kind=table table=target schema=db catalog=awsdatacatalog]]",
        "column[name=col3 type=VARCHAR properties=[kind=table table=tbl schema=db catalog=awsdatacatalog]]",
    ]
    assert len(h.edges) == 1
