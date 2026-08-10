import os
import sys

from sqlglot import exp

from sqlleaf.models.query import UserDefinedFunctionQuery
from tests.new_fixtures import holder as holder
from tests.new_fixtures import to_sql as to_sql

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIALECT = "postgres"


def test__udf_variadic_parameter(holder):
    sql = """
    CREATE FUNCTION hello(greeting TEXT, VARIADIC names TEXT[])
    RETURNS TEXT AS $$
        SELECT greeting || ' ' || string_agg(unpacked_name, ' and ')
        FROM unnest(names) AS unpacked_name;
    $$ LANGUAGE SQL;

    CREATE TABLE target(name1 VARCHAR);
    INSERT INTO target (name1) SELECT hello('Hi', 'Alice', 'Bob', 'Charlie');
    """

    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[0].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "hello"
    assert query.schema_name is None
    assert query.return_columns == []
    assert query.return_type == exp.DataType.build("TEXT")
    assert query.language == "sql"

    assert len(query.parameters) == 2
    assert query.parameters[0].name == "greeting"
    assert not query.parameters[0].is_variadic
    assert query.parameters[1].name == "names"
    assert query.parameters[1].is_variadic

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (name1) "
        "SELECT (SELECT 'Hi ' || STRING_AGG(unpacked_name.unpacked_name, ' and ') AS _col_0 "
        "FROM UNNEST(ARRAY['Alice', 'Bob', 'Charlie']) AS unpacked_name) AS name1"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert sorted(h.paths) == [
        ['literal[" and "]', "function[GROUP_CONCAT]", "function[DPIPE]", "column[target.name1]"],
        ['literal["Hi "]', "function[DPIPE]", "column[target.name1]"],
        [
            "literal[{'Alice','Bob','Charlie'}]",
            "function[UNNEST]",
            "column[unpacked_name.unpacked_name]",
            "function[GROUP_CONCAT]",
            "function[DPIPE]",
            "column[target.name1]",
        ],
    ]


common_objects = """
CREATE TABLE target(age INT);

CREATE FUNCTION mleast(VARIADIC arr NUMERIC[]) RETURNS NUMERIC AS $$
    SELECT min($1[i]) FROM generate_subscripts($1, 1) g(i);
$$ LANGUAGE SQL;
"""


def test__udf_mleast_variadic_parameter_cte(holder):
    sql = f"""
    {common_objects}

    -- Variadic array from CTE
    INSERT INTO target (age)
    WITH data_source AS (
        SELECT ARRAY[10, -1, 5, 4.4]::numeric[] AS my_array
    )
    SELECT mleast(VARIADIC my_array) FROM data_source;
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (age) WITH data_source AS (SELECT CAST(ARRAY[10, -1, 5, 4.4] AS DECIMAL[]) AS my_array) SELECT (SELECT MIN(data_source.my_array[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(my_array, 1) AS g(i)) AS age FROM data_source AS data_source"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert h.paths == [
        [
            "literal[{10,-1,5,4.4}]",
            "function[CAST]",
            "column[data_source.my_array]",
            "function[MIN]",
            "column[target.age]",
        ]
    ]
    assert h.nodes_full == [
        "function[name=CAST type=ARRAY<DECIMAL> position=[query_depth=1 query_width=1 statement=2 select=0 func_depth=0 func_arg=0]]",
        "function[name=MIN type=DECIMAL position=[query_depth=1 query_width=0 statement=2 select=0 func_depth=0 func_arg=0]]",
        "literal[name={10,-1,5,4.4} type=ARRAY<DOUBLE> position=[query_depth=1 query_width=1 statement=2 select=0 func_depth=1 func_arg=0]]",
        "column[name=my_array type=ARRAY<DECIMAL> properties=[kind=cte table=data_source statement=2]]",
        "column[name=age type=INT properties=[kind=table table=target]]",
    ]


def test__udf_mleast_variadic_parameter_empty(holder):
    sql = f"""
    {common_objects}

    -- Empty array
    INSERT INTO target (age) SELECT mleast(VARIADIC ARRAY[]::numeric[]);
    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (age) SELECT (SELECT MIN((CAST(ARRAY[] AS DECIMAL[]))[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(CAST(ARRAY[] AS DECIMAL[]), 1) AS g(i)) AS age"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert h.paths == [["literal[{}]", "function[CAST]", "function[MIN]", "column[target.age]"]]


def test__udf_mleast_variadic_parameter_array(holder):
    sql = f"""
    {common_objects}

    -- Variadic array
    INSERT INTO target (age) SELECT mleast(VARIADIC ARRAY[10, -1, 5, 4.4]);

    """
    h = holder(sql=sql, dialect=DIALECT)

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert h.paths == [["literal[{10,-1,5,4.4}]", "function[MIN]", "column[target.age]"]]


def test__udf_mleast_variadic_parameter_args(holder):
    sql = f"""
    {common_objects}

    -- Variadic args
    INSERT INTO target (age) SELECT mleast(10, -1, 5, 4.4);
    """
    h = holder(sql=sql, dialect=DIALECT)

    query = h.holders[1].original
    assert isinstance(query, UserDefinedFunctionQuery)

    assert query.function_name == "mleast"
    assert query.schema_name is None
    assert query.return_columns == []
    assert query.return_type == exp.DataType.build("numeric")
    assert query.language == "sql"

    assert len(query.parameters) == 1
    assert query.parameters[0].name == "arr"
    assert query.parameters[0].is_variadic

    insert_query = h.holders[2]
    insert_after = [
        "INSERT INTO target (age) SELECT (SELECT MIN((ARRAY[10, -1, 5, 4.4])[g.i]) AS _col_0 FROM GENERATE_SUBSCRIPTS(ARRAY[10, -1, 5, 4.4], 1) AS g(i)) AS age"
    ]
    actual_after = [insert_query.transformed.statement]
    assert to_sql(actual_after, dialect=DIALECT) == insert_after

    assert h.paths == [["literal[{10,-1,5,4.4}]", "function[MIN]", "column[target.age]"]]
