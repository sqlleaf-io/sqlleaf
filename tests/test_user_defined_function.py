"""
Tests taken from:
https://github.com/tobymao/sqlglot/blob/main/tests/dialects/test_postgres.py
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))


DIALECT = "postgres"

tests = [
    # no schema
    """
CREATE FUNCTION a_plus_b(a integer, b integer default 42) RETURNS integer
    LANGUAGE SQL
    RETURN 4;
""",
    # with schema
    """
CREATE FUNCTION my.a_plus_b(a integer, b integer default 42) RETURNS integer
    LANGUAGE SQL
    RETURN 4;
""",
    # allow null input
    """
CREATE FUNCTION my.a_plus_b(a integer, b integer default 42) RETURNS integer
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    RETURN 4;
""",
    # return variable
    """
CREATE FUNCTION my.a_plus_b(a integer, b integer default 42) RETURNS integer
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    RETURN a;
""",
    # return two variables
    """
CREATE FUNCTION my.a_plus_b(a integer, b integer default 42) RETURNS integer
    LANGUAGE SQL
    RETURNS NULL ON NULL INPUT
    RETURN a + b;
""",
]

q = "INSERT INTO fruit.processed SELECT my.a_plus_b(2,3) as age"
"""
INSERT INTO fruit.processed
SELECT
    my.func() as name1
    my.function(name) as name2,
    my.func(my.func(kind)) as name3
FROM fruit.raw;
"""

"""
-- Different aliasing techniques
SELECT * 
FROM calculation_func(10, 5) AS f(total, multiplied);
    
SELECT sum AS total, product AS multiplied 
FROM calculation_func(10, 5);

"""
