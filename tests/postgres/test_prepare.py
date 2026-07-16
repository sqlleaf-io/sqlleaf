import os
import sys

import pytest
from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import PrepareQuery, ExecuteQuery
from sqlleaf.typing import SqlObjectType
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "postgres"


def test__prepare(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);

    PREPARE my_plan AS SELECT * FROM source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    # PREPARE should not produce any lineage
    assert h.paths == []
    assert h.nodes_full == []
    assert len(h.edges) == 0

    # It should be stored in the mapping
    from sqlglot import exp
    mapping = h.lineage.object_mapping
    prepare_query = mapping.lookup_prepare_query(exp.to_table("my_plan"))
    assert prepare_query is not None
    assert isinstance(prepare_query, PrepareQuery)
    # The statement is qualified, so SELECT * becomes SELECT source.name, ...
    sql_generated = prepare_query.statement.sql(dialect=DIALECT)
    assert "source" in sql_generated.lower()
    assert "name" in sql_generated.lower()
    assert "amount" in sql_generated.lower()




def test__prepare_invalid_syntax_fails(holder):
    sql = "PREPARE my_plan SELECT * FROM source;"
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
    assert h.collected_queries.unsupported[0][1].name == "PREPARE"


def test__execute(holder):
    sql = """
    CREATE TABLE source(name VARCHAR, amount INT);
    CREATE TABLE target(name VARCHAR, amount INT);

    PREPARE my_plan AS INSERT INTO target SELECT * FROM source;
    EXECUTE my_plan;
    """
    h = holder(sql=sql, dialect=DIALECT)
    prepare_query: PrepareQuery = h.holders[2].original
    assert prepare_query.source_info.type == SqlObjectType.DML
    assert prepare_query.target_info.type == SqlObjectType.NONE

    execute_query: ExecuteQuery = h.holders[3].transformed
    assert execute_query.source_info is None
    assert execute_query.target_info.type == SqlObjectType.PREPARED_STATEMENT

    assert h.paths == [
        ["column[source.name]", "column[target.name]"],
        ["column[source.amount]", "column[target.amount]"],
    ]
    assert len(h.edges) == 2


# TODO: ensure the below (see test_ctas.py for similar "CTAS .. EXECUTE" tests)
"""
# OK
PREPARE my_plan AS INSERT INTO target SELECT 'Hello';
EXECUTE my_plan;

# ERROR: wrong number of parameters for prepared statement (expected: 1, actual: 0)
PREPARE my_plan AS INSERT INTO target SELECT $1;
EXECUTE my_plan;

# OK
PREPARE my_plan AS INSERT INTO target SELECT $1;
EXECUTE my_plan(5);

# ERROR: wrong number of parameters for prepared statement (expected: 1, actual: 2)
PREPARE my_plan AS INSERT INTO target SELECT $1;
EXECUTE my_plan(5, 6);

# ERROR: wrong number of parameters for prepared statement (expected: 2, actual: 1)
PREPARE my_plan AS INSERT INTO target SELECT $1, $2;
EXECUTE my_plan(5);

# OK (if no parameters are defined using dollar symbol, any excess parameters are ignored)
PREPARE my_plan AS INSERT INTO target SELECT 'Hello';
EXECUTE my_plan(5);
"""


def test__execute_missing_parameter_fails(holder):
    sql = """
    CREATE TABLE target(name VARCHAR, amount INT);
    PREPARE my_plan AS INSERT INTO target(name) SELECT $1;
    EXECUTE my_plan;
    """
    with pytest.raises(SqlLeafException, match=r"Wrong number of parameters for prepared statement \(expected: 1, actual: 0\)"):
        holder(sql=sql, dialect=DIALECT)


def test__execute_missing_prepare_fails(holder):
    sql = "EXECUTE non_existent_plan;"
    with pytest.raises(SqlLeafException, match="Could not find PREPARE statement for plan: non_existent_plan"):
        holder(sql=sql, dialect=DIALECT)


def test__execute_invalid_syntax_fails(holder):
    sql = "EXECUTE a b;"
    with pytest.raises(SqlLeafException, match="Invalid syntax for EXECUTE expression: EXECUTE a b"):
        holder(sql=sql, dialect=DIALECT)
