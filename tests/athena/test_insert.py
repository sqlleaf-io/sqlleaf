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
