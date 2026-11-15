import os
import sys

from sqlglot import exp

from sqlleaf.models.query import UserDefinedFunctionQuery
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "mysql"


def to_sql(expressions: list[exp.Expr]) -> list[str]:
    return [e.sql(dialect=DIALECT) for e in expressions]


def test__udf_insert_and_return(holder):
    sql = """
    CREATE TABLE t2 (v INT);
    CREATE FUNCTION f1(p1 INT) RETURNS INT
      BEGIN
        INSERT INTO t2 VALUES (p1);
        RETURN p1;
      END;

    CREATE TABLE target (v INT);
    INSERT INTO target (v) SELECT f1(7);
    """
    h = holder(sql=sql, dialect=DIALECT)

    assert len(h.lineage.collected_queries.unsupported) == 0

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "f1"
    assert query.schema_name is None
    assert query.return_type == exp.DataType.build("INT", dialect=DIALECT)
    assert [p.name for p in query.parameters] == ["p1"]

    insert_query = h.holders[3]
    assert to_sql([insert_query.transformed.statement]) == ["INSERT INTO target (v) SELECT (SELECT 7 AS `7`) AS v"]
