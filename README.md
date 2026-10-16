# sqlleaf
## Trace your data
sqlleaf is a tool to help you to understand how your data flows across your data systems by producing detailed, column-level lineage across any SQL query and dialect.

It extends beyond traditional lineage tools by mapping relationships across all kinds of expressions, such as columns, functions, literals and variables.

## Example
Given some SQL queries in a file that insert data from one table into another:
```sql
-- File: example.sql
CREATE TABLE users (name VARCHAR(50), birthday DATE);
CREATE TABLE logins (name VARCHAR(50));

INSERT INTO users (name, birthday)
SELECT LOWER(name) AS name, CURRENT_TIMESTAMP AS birthday
FROM logins;
```
And some Python code:
```python
sql = open("example.sql").read()

import sqlleaf
lineage = sqlleaf.Lineage()
lineage.generate(sql=sql, dialect="postgres")
lineage.print_paths()
```
We can generate its lineage as a set of paths:
```
column[logins.name] -> function[LOWER] -> column[users.name]
function[CURRENT_TIMESTAMP] -> column[users.birthday]
```

## Applications
sqlleaf allows you to build a wide range of new applications on top of SQL databases, such as:
- data tracing and tagging systems, such as personally identifiable information tracking
- lineage-based SQL validators
- auditing systems and historical analysis
- identification of unused columns and tables
- support for database migration correctness
- impact analysis of changes to queries

## Features
### Types of queries
sqlleaf traces lineage across a wide range of DML queries, such as INSERT, UPDATE, MERGE, CTAS, COPY, UNLOAD, CTEs, and many more.

It parses over 30 dialects, extending functionality from the underlying SQL transpiler `sqlglot`.

Some basic queries:
```postgresql
-- Basic CTAS
CREATE TABLE dst AS SELECT * FROM source;

-- Basic UPDATE
UPDATE dst t SET first_name = 'john', age = s.age FROM src s;

-- An INSERT with a CTE (Common Table Expression)
WITH my_cte AS (SELECT 1 AS num) INSERT INTO dst (age) SELECT c.num FROM my_cte c;
```

### Support for dynamic SQL inside PL/pgSQL
You can trace lineage across variables and complex, dynamically constructed statements. This works by analyzing the procedure's inner statements, substituting any arguments and variables, and transforming the statements into the desired queries.

For example, given a query to calculate the row count of an arbitrary table:
```postgresql
-- Define a PL/pgSQL procedure in Postgres
CREATE PROCEDURE get_maximum_id(schema_name TEXT, table_name TEXT)
AS $$
BEGIN
    EXECUTE format('INSERT INTO target (my_value) SELECT MAX(id) FROM %I.%I', schema_name, table_name);
END;
$$ LANGUAGE plpgsql;

-- Call it
CALL get_maximum_id('public', 'users');
```
sqlleaf extracts and transforms this into the statement:
```postgresql
INSERT INTO target (my_value) SELECT MAX(id) FROM public.users;
```
and then generates its lineage:
```
column[public.users.id] -> function[MAX] -> column[target.my_value]
```

### User-defined functions, procedures and types
Given a user-defined function or a procedure, sqlleaf will extract the statement's inner queries so that they can be referenced by the calling query:
```postgresql
-- Create the function
CREATE FUNCTION hello() RETURNS TEXT AS $$
    SELECT 'Hello';
$$ LANGUAGE SQL;

-- Insert its value into a new table
CREATE TABLE target (my_name VARCHAR);
INSERT INTO target (my_name) SELECT hello();
```
This will perform inline transformations to produce a new query:
```postgresql
INSERT INTO target (my_name) SELECT (SELECT 'hello') AS name;
```
with lineage:
`literal['Hello'] -> column[target.name]`

### Pivot, Unpivot
Complex transformations such as pivots, unpivots, laterals and table functions are supported.

## Customization
You can bring your own logic for processing SQL expressions and their nodes. 

For example, let's say you only want to include certain functions inside the lineage graph, such as `SUM()`. You would do this by defining a *user-defined hook* and that excludes everything except `SUM()`:
```python
import sqlleaf
lineage = sqlleaf.Lineage()

from sqlleaf.lineage import Hook
from sqlleaf.models.node import FunctionNode

# Register a hook that only collects certain functions
hook = Hook(name="only_sum", kind=FunctionNode, func=lambda n: n.name == "SUM")
lineage.register_hooks(hooks=[hook])
```
When you run `lineage.generate()`, the only functions that are included as nodes are those named `SUM`.

## Searching the lineage
To map the lineage into a graph, sqlleaf is built on top of the popular library `networkx`.
If you need to search the graph, you can use any of network'x graph traversal functions.
There are currently no dedicated search APIs for sqlleaf. These will be developed in an upcoming major release.

There are various functions for printing the lineage: `print_paths()`, `print_tree()`, and `print_json()`.


## Examples
Below are examples of SQL queries and their corresponding lineages.

#### 1. Simple INSERT
```postgresql
INSERT INTO dst (name) VALUES (3);
```
`literal[3] -> column[dst.name]`

#### 2. JSONPath selectors
```postgresql
 INSERT INTO dst SELECT jsonblob ->> 'fruits' -> 'apple' AS name FROM src;
```
`column[src.name] → jsonpath[.fruits.apple] → column[dst.name]`

#### 3. Using variables via SET
```snowflake
SET b = 'src';
CREATE TABLE dst AS SELECT col1 FROM IDENTIFIER($b);
```
`column[SRC.COL1] → column[DST.COL1]`

#### 4. COPY queries
```postgresql
COPY dst TO STDOUT;
```
`column[dst.col1] → stream[stdout]` \
`column[dst.col2] → stream[stdout] `

```postgresql
COPY dst TO PROGRAM 'gzip > /tmp/data.csv.gz';
```
`column[dst.col1] → program[gzip]` \
`column[dst.col2] → program[gzip] `

#### 5. UNLOAD query
```redshift
UNLOAD ('SELECT name FROM src') TO 's3://dst-bucket/name-prefix' IAM_ROLE '...';
```
`column[src.name] → column[name path=s3://dst-bucket/name-prefix]`

#### 6. Sequences
```postgresql
CREATE SEQUENCE my_serial START 101;
INSERT INTO dst (age) SELECT nextval('my_serial') as age;
```
`sequence[my_serial] → column[dst.age]`

#### 7. An UPDATE with inner CTEs containing UPDATEs that return their old and new columns
```postgresql
WITH first_cte AS (
    UPDATE fruit.raw
    SET name = 'pear'
    RETURNING age, old.age as old_age, new.age as new_age
),
second_cte AS (
    UPDATE fruit.raw AS r
    SET name = 'tomato'
    RETURNING *, OLD.*, NEW.*
)
UPDATE fruit.processed
SET age = first_cte.age
FROM first_cte;
```
`column[fruit.raw.age] -> column[first_cte.age] -> column[fruit.processed.age]` \
`literal["pear"] -> column[fruit.raw.name]` \
`literal["tomato"] -> column[fruit.raw.name`

## Limitations
- Many of the dialects are incomplete. Postgres and PL/pgSQL have been mapped out extensively, but most of the dialects do not have their own specific features parsed into graphs yet. Dialects that do have features are Athena, Redshift, MySQL and Snowflake; the others have not been implemented at all yet.

- sqlleaf does not support data deletion. Statements like `DELETE`, `TRUNCATE` or `DROP TABLE` currently have no effect. They will in the future.
