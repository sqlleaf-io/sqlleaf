import os
import sys

from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


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
        "pivot[name= properties=[target=john statement=2]]",
        "function[name=SUM type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "column[name=amount type=INT properties=[kind=derived_table table=_0 statement=2]]",
        "column[name=amount type=INT properties=[kind=table table=source]]",
        "column[name=john_total type=INT properties=[kind=table table=target]]",
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
        "pivot[name= properties=[source=total target=john_total statement=2]]",
        "pivot[name= properties=[source=average target=john_average statement=2]]",
        "pivot[name= properties=[source=total target=mary_total statement=2]]",
        "pivot[name= properties=[source=average target=mary_average statement=2]]",
        "function[name=AVG type=DOUBLE position=[query_depth=0 query_width=0 statement=2 select=1 func_depth=0 func_arg=0]]",
        "function[name=AVG type=DOUBLE position=[query_depth=0 query_width=0 statement=2 select=3 func_depth=0 func_arg=0]]",
        "function[name=SUM type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "function[name=SUM type=BIGINT position=[query_depth=0 query_width=0 statement=2 select=2 func_depth=0 func_arg=0]]",
        "column[name=age type=INT properties=[kind=derived_table table=_0 statement=2]]",
        "column[name=amount type=INT properties=[kind=derived_table table=_0 statement=2]]",
        "column[name=age type=INT properties=[kind=table table=source]]",
        "column[name=amount type=INT properties=[kind=table table=source]]",
        "column[name=john_average type=DECIMAL(10, 2) properties=[kind=table table=target]]",
        "column[name=john_total type=INT properties=[kind=table table=target]]",
        "column[name=mary_average type=DECIMAL(10, 2) properties=[kind=table table=target]]",
        "column[name=mary_total type=INT properties=[kind=table table=target]]",
    ]
    assert len(h.edges) == 14


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
        "unpivot[name= properties=[target=name statement=2]]",
        "unpivot[name= properties=[source=john_total target=amount statement=2]]",
        'literal[name="john" type=VARCHAR position=[query_depth=0 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]',
        "column[name=john_total type=INT properties=[kind=table table=source]]",
        "column[name=amount type=INT properties=[kind=table table=target]]",
        "column[name=name type=VARCHAR properties=[kind=table table=target]]",
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
