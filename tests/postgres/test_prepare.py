import os
import sys

import pytest
from sqlleaf.exception import SqlLeafException
from sqlleaf.models.query import PrepareQuery
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


def test__prepare_with_arguments_fails(holder):
    sql = "PREPARE my_plan (int) AS SELECT * FROM source;"
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
    assert h.collected_queries.unsupported[0][1].name == "PREPARE"


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

    # EXECUTE should produce lineage
    assert h.paths == [
        ["column[source.name]", "column[target.name]"],
        ["column[source.amount]", "column[target.amount]"],
    ]
    assert len(h.edges) == 2


def test__execute_missing_prepare_fails(holder):
    sql = "EXECUTE non_existent_plan;"
    with pytest.raises(SqlLeafException, match="Could not find PREPARE statement for plan: non_existent_plan"):
        holder(sql=sql, dialect=DIALECT)


def test__execute_with_arguments_fails(holder):
    sql = "EXECUTE my_plan(1);"
    h = holder(sql=sql, dialect=DIALECT)
    assert len(h.collected_queries.unsupported) == 1
    assert h.collected_queries.unsupported[0][1].name == "EXECUTE"


def test__execute_invalid_syntax_fails(holder):
    sql = "EXECUTE a b;"
    with pytest.raises(SqlLeafException, match="Invalid syntax for EXECUTE expression: EXECUTE a b"):
        holder(sql=sql, dialect=DIALECT)
