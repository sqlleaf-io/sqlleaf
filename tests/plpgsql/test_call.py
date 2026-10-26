import os
import sys

import pytest
import sqlglot

from sqlleaf import exception
from sqlleaf.models.query import (
    InsertQuery,
    QueryHolder,
)
from tests.new_fixtures import holder as holder

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


DIALECT = "plpgsql"


def _find_insert_query(holder: QueryHolder) -> InsertQuery | None:
    if isinstance(holder.original, InsertQuery):
        return holder.transformed
    for child_holder in holder.downstream_holders:
        insert_query = _find_insert_query(child_holder)
        if insert_query is not None:
            return insert_query
    return None


def _find_single_insert_query(h) -> InsertQuery:
    insert_queries = [insert_query for holder in h.holders if (insert_query := _find_insert_query(holder)) is not None]
    assert len(insert_queries) == 1
    return insert_queries[0]


def test_call_out_parameter_propagates_to_caller(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE greet(greeting_in TEXT, OUT greeting VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        greeting := greeting_in || ' John';
    END;
    $$;

    DO $$
    DECLARE b VARCHAR;
    BEGIN
        CALL greet('hello', b);
        INSERT INTO target (name) SELECT b AS name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = block_holder.downstream_holders[2].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'hello John' AS name"


def test_call_inout_parameter_starts_with_caller_value(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE append_mark(INOUT value VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        value := value || '!';
    END;
    $$;

    DO $$
    DECLARE b VARCHAR := 'hello';
    BEGIN
        CALL append_mark(b);
        INSERT INTO target (name) SELECT b AS name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = block_holder.downstream_holders[2].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'hello!' AS name"


def test_call_multiple_out_parameters_propagate_independently(holder):
    sql = """
    CREATE TABLE target (name TEXT, age INTEGER);

    CREATE PROCEDURE set_values(OUT result_name VARCHAR, OUT result_age INTEGER)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        result_name := 'hello';
        result_age := 42;
    END;
    $$;

    DO $$
    DECLARE b VARCHAR;
        c INTEGER;
    BEGIN
        CALL set_values(b, c);
        INSERT INTO target (name, age) SELECT b, c;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = block_holder.downstream_holders[3].transformed
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name, age) SELECT 'hello' AS name, 42 AS age"
    )


def test_call_in_parameter_reassignment_does_not_propagate(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE mutate(value VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        value := value || '!';
    END;
    $$;

    DO $$
    DECLARE b VARCHAR := 'caller';
    BEGIN
        CALL mutate('procedure');
        INSERT INTO target (name) SELECT b AS name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[2].downstream_holders[0]
    insert_query: InsertQuery = block_holder.downstream_holders[2].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'caller' AS name"


def test_call_nesteds_keep_parameter_scopes_independent(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE inner_proc(INOUT inner_value VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        inner_value := inner_value || ' inner';
    END;
    $$;

    CREATE PROCEDURE outer_proc(INOUT outer_value VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        CALL inner_proc(outer_value);
        outer_value := outer_value || ' outer';
    END;
    $$;

    DO $$
    DECLARE b VARCHAR := 'start';
    BEGIN
        CALL outer_proc(b);
        INSERT INTO target (name) SELECT b AS name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    block_holder: QueryHolder = h.holders[3].downstream_holders[0]
    insert_query: InsertQuery = block_holder.downstream_holders[2].transformed
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'start inner outer' AS name"


def test_call_out_parameter_shadows_same_named_caller_variable(holder):
    sql = """
    CREATE TABLE target (name TEXT, other_name TEXT);

    CREATE PROCEDURE set_name(OUT result VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        result := 'new';
    END;
    $$;

    DO $$
    DECLARE result TEXT := 'keep';
        other_name TEXT;
    BEGIN
        CALL set_name(other_name);
        INSERT INTO target (name, other_name) SELECT result, other_name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name, other_name) SELECT 'keep' AS name, 'new' AS other_name"
    )


def test_call_inout_parameter_shadows_same_named_caller_variable(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE append_mark(INOUT result VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        result := result || '!';
    END;
    $$;

    DO $$
    DECLARE result TEXT := 'before';
    BEGIN
        CALL append_mark(result);
        INSERT INTO target (name) SELECT result;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'before!' AS name"


def test_call_out_parameter_is_null_before_assignment(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE read_out(OUT result VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        INSERT INTO target (name) SELECT result;
    END;
    $$;

    DO $$
    DECLARE output_name TEXT;
    BEGIN
        CALL read_out(output_name);
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT NULL AS name"


def test_call_positional_parameter_with_out_parameter(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE set_name(prefix VARCHAR, OUT result VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        result := $1 || '!';
    END;
    $$;

    DO $$
    DECLARE output_name TEXT;
    BEGIN
        CALL set_name('before', output_name);
        INSERT INTO target (name) SELECT output_name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'before!' AS name"
    assert h.paths == [['literal["before!"]', "column[target.name]"]]


def test_call_in_argument_expression_resolves_caller_variable(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE copy_name(value TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        INSERT INTO target (name) SELECT value;
    END;
    $$;

    DO $$
    DECLARE b TEXT := 'hello';
    BEGIN
        CALL copy_name(b || 'x');
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'hellox' AS name"


def test_call_positional_reference_uses_resolved_argument_expression(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE copy_name(value TEXT, OUT result TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        result := $1 || '!';
    END;
    $$;

    DO $$
    DECLARE b TEXT := 'hello';
        output_name TEXT;
    BEGIN
        CALL copy_name(b || 'x', output_name);
        INSERT INTO target (name) SELECT output_name;
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'hellox!' AS name"


def test_call_nested_resolves_outer_parameter_expression(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE inner_proc(value TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        INSERT INTO target (name) SELECT value;
    END;
    $$;

    CREATE PROCEDURE outer_proc(INOUT value TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        CALL inner_proc(value || '-');
    END;
    $$;

    DO $$
    DECLARE b TEXT := 'hello';
    BEGIN
        CALL outer_proc(b);
    END;
    $$;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert insert_query.statement.sql(dialect=DIALECT) == "INSERT INTO target (name) SELECT 'hello-' AS name"


def test_call_nested_cannot_see_outer_parameter(holder):
    sql = """
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE inner_proc()
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        INSERT INTO target (name) SELECT secret;
    END;
    $$;

    CREATE PROCEDURE outer_proc(secret TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        CALL inner_proc();
    END;
    $$;

    CALL outer_proc('leak');
    """
    with pytest.raises(sqlglot.errors.OptimizeError):
        holder(sql=sql, dialect=DIALECT)


def test_call_exception_discards_output_writeback(holder):
    sql = """
    CREATE PROCEDURE fail(OUT result VARCHAR)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        missing_value := 'body';
    END;
    $$;

    DO $$
    BEGIN
        CALL fail(missing_output);
    END;
    $$;
    """
    with pytest.raises(exception.MappingError, match='"missing_value"'):
        holder(sql=sql, dialect=DIALECT)


def test_call_parameter_does_not_replace_qualified_column(holder):
    sql = """
    CREATE TABLE source (name TEXT);
    CREATE TABLE target (name TEXT);

    CREATE PROCEDURE copy_name(name TEXT)
    LANGUAGE PLPGSQL
    AS $$
    BEGIN
        INSERT INTO target (name) SELECT source.name FROM source;
    END;
    $$;

    CALL copy_name('parameter');
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = _find_single_insert_query(h)
    assert (
        insert_query.statement.sql(dialect=DIALECT)
        == "INSERT INTO target (name) SELECT source.name AS name FROM source AS source"
    )
    assert h.paths == [["column[source.name]", "column[target.name]"]]
