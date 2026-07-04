import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "redshift"


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
        "column[name=amount type=INT properties=[kind=view table=my_view]]",
        "column[name=name type=VARCHAR properties=[kind=view table=my_view]]",
        "column[name=amount type=INT properties=[kind=table table=source]]",
        "column[name=name type=VARCHAR properties=[kind=table table=source]]",
    ]
    assert len(h.edges) == 2
