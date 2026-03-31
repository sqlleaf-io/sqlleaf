# sqlleaf
Extract detailed column-level lineage and SQL functions from SQL statements.

This extends the wonderful open source SQL transpiler [sqlglot](https://github.com/tobymao/sqlglot) with the following features:
- detailed column-level lineage with columns, views, functions, literals and other objects as data sources 
- extraction of SQL functions - their names, arguments and positions
- parsing of stored procedures and user-defined functions
- representation of SQL queries as networkx graphs for simple analysis
- useful traversal functions for common lineage use cases

### Contents
* [Example](#example)
* [Introduction](#intro)
* [Supported queries](#node-types)
  * [Insert, Update and Merge](#insert-update-and-merge)
  * [Functions](#functions)
  * [Common Table Expressions](#common-table-expressions-ctes)
  * [Views, Select Into, Create Table As](#views-select-into-and-create-table-as-ctas)
  * [JSON](#json)
  * [Stored procedures](#stored-procedures)
  * [User defined functions](#user-defined-functions)
  * [Triggers](#triggers)
  * [Sequences](#sequences)
* [Extending](#extending)
* [Additional methods](#additional-methods)
* [Roadmap](#roadmap)

## Example

```python
sql = """
CREATE TABLE source (name VARCHAR);
CREATE TABLE target (name VARCHAR, age INT, birthday TIMESTAMP);

INSERT INTO target
SELECT LOWER(name) AS name, 5 as age, CURRENT_TIMESTAMP as birthday
FROM source;
"""
import sqlleaf
lineage = sqlleaf.Lineage()
lineage.generate(sql=sql, dialect="postgres")
lineage.print_tree()
```
Output:
```
column[target.name]
└── function[LOWER()]
    └── column[source.name]
column[target.age]
└── literal[5]
column[target.birthday]
└── function[CURRENTTIMESTAMP()]
```

Dozens of dialects are supported. For the full list, see the [sqlglot](https://github.com/tobymao/sqlglot) project page.

## Introduction
The goal is to understand how data flows throughout a database purely via static analysis of SQL queries.

In order to have complete knowledge of how data flows in a system, we have to know all its data sources.

sqlleaf is different from other lineage systems in that it calculates lineage from non-column sources of information.

There are many open-source tools that can calculate column-level lineage, such as [sqllineage](https://github.com/reata/sqllineage), [sqlglot](https://github.com/tobymao/sqlglot/blob/main/sqlglot/lineage.py), and [DataHub](https://github.com/datahub-project/datahub/blob/master/docs/api/tutorials/lineage.md),  but they all fall short: they only consider columns. They ignore non-column sources of data, such as functions, literals or variables, which are essential to explaining how data flows throughout a system.

For example, consider the SQL snippet:
```postgresql
INSERT INTO fruit.processed
SELECT
    CASE WHEN age < 2 THEN 'new' ELSE 'old' END AS kind
FROM fruit.raw
```

Some tools detect that the column `age` is used and would therefore produce lineage:
- `column[fruit.raw.age] -> column[fruit.processed.kind]`

However, we would expect the lineage to be the following:
- `literal["new"] -> column[fruit.processed.kind]`
- `literal["old"] -> column[fruit.processed.kind]`

sqlleaf considers the context in which columns appear and ignores values which aren't relevant to data movement.
Other examples in which columns are excluded are those appearing in `WHERE`, `ORDER BY`, and `PARTITION BY` clauses.

Similarly, consider the query:
```postgresql
INSERT INTO accounts
SELECT SUBSTRING(credit_card, 0, 3)
FROM customers;
```
Other systems ignore the context of the function and create lineage:
- `column[customers.credit_card] -> column[transactions.credit_card]`

whereas sqlleaf creates a dedicated node for the function:
- `column[customers.credit_card] -> function[substring] -> column[transactions.credit_card]`

along with methods to easily traverse and find these types of situations.

## Usage
There is one main function:
- `generate()`, which converts SQL expressions into graphs

### generate()

You may pass as many SQL statements as you wish to the `generate()` function. Each statement is converted to a networkx MultiDiGraph,
and then merged into the main graph that contains all the other statements' nodes and edges.

You can also call `generate()` multiple times if you need to use different dialects:
```python
lineage.generate(sql="""INSERT INTO fruit.raw SELECT 'apple' AS name;""", dialect="snowflake");
lineage.generate(sql="""INSERT INTO bakery.raw SELECT 'bread' AS name;""", dialect="redshift");
```
*Note:* currently, every table that is used throughout your queries *must* be defined and passed to `generate()`.

## Supported queries
sqlleaf aims to represent any type of query or object from any SQL dialect.

### Insert, Update and Merge
sqlleaf can extract queries from insert, update and merge statements.

For example, the merge statement:
```postgresql
MERGE INTO fruit.processed AS t
    USING fruit.raw AS s
    ON t.kind = s.kind
    WHEN MATCHED THEN UPDATE SET name = s.name
    WHEN NOT MATCHED THEN INSERT (label) VALUES (s.kind);
```
has tree output:
```
column[fruit.processed.name]
└── column[fruit.raw.name]
column[fruit.processed.label]
└── column[fruit.raw.kind]
```
Internally, the merge query has two inner queries: one insert and one update. Queries form a hierarchy, depending on their type, allowing you to traverse them easily:
```python
query = lineage.get_queries()   # [structs.MergeQuery]
query.child_queries             # [structs.UpdateQuery, structs.InsertQuery]
```

### Common Table Expressions (CTEs)
CTEs are treated as nodes.
```postgresql
WITH my_cte AS ( SELECT 'john' as name )
INSERT INTO processed
SELECT name as name FROM my_cte;
```
```
column[fruit.processed.name]
└── column[my_cte.name]
    └── literal["john"]
```

### Views, Select Into, and Create Table As (CTAS)
You can generate lineage for views, 'select into' and CTAS statements:
```python
lineage.generate(text="CREATE VIEW my_view AS SELECT kind FROM fruit.raw;", dialect="postgres")
lineage.print_tree(full_name=True)
```
```
column[my_view.kind type=VARCHAR kind=view]
└── column[fruit.raw.kind type=VARCHAR kind=table]
```
A `SELECT INTO` query is automatically transformed by sqlglot into a `CTAS`
if the dialect officially recommends it (e.g. Postgres).

### Functions
A lineage system needs to keep track of whether data are transformed as they move throughout tables.
sqlleaf represents functions as nodes in the graph.

### JSON
Paths and operators used for JSON are treated as nodes:
```postgresql
INSERT INTO processed
SELECT jsonblob -> 'fruits' -> 'apple' as name
FROM raw;
```
```
column[processed.name]
└── jsonpath[.fruits.apple]
    └── column[raw.jsonblob]
```
Coming soon: XML

### Stored procedures
The current SQL parsers lack complete support for stored procedure syntax, such as PL/pgsql. `sqlleaf` will perform a best effort to extract any queries inside them.

This example parses a stored procedure containing a CTE, an input variable and several nested functions:

```postgresql
CREATE OR REPLACE PROCEDURE fruit.process(v_kind VARCHAR, v_amount INT)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$

DECLARE
    BEGIN

    WITH cte AS (
        SELECT upper(kind) AS knd
        FROM fruit.raw
    )
    INSERT INTO fruit.processed
    SELECT v_amount     as amount,
           1            as number,
           lower(c.knd) as kind
    FROM cte c;

    EXCEPTION WHEN OTHERS THEN
    SELECT 1;
    END;
$$;
```
```
column[fruit.processed.kind]
└── function[LOWER()]
    └── column[cte.knd]
        └── function[UPPER()]
            └── column[fruit.raw.kind]
column[fruit.processed.amount]
└── variable[v_amount]
column[fruit.processed.number]
└── literal[1]
```

### User Defined Functions
Coming soon.

### Triggers
Triggers are parsed and collected, but their behaviour is not currently implemented.
Coming soon.

### Sequences
Sequences (in Postgres) are supported as nodes.

```postgresql
CREATE SEQUENCE serial START 101;
INSERT INTO processed SELECT nextval('serial') as age;
```
```
column[processed.age]
└── sequence[fruit.raw.kind type=VARCHAR kind=table]
```

# Extending
You can add your own functionality for per-dialect processing functions:

```python
from sqlleaf.structs import LineageBuilder
from sqlleaf.structs import ColumnNode

class MyCustomBuilder(LineageBuilder):
    dialect = 'my_dialect'
    
    # Example: Override the Column node creation logic
    def process_column(self, processor_ctx, ctx):
        # Add your logic here...
        node_attrs = ColumnNode(table='my_table', column='my_column', ...)
        children = []
        return node_attrs, children
```

# Additional methods
The main Lineage class offers some helper methods:

- `lineage.get_edges()` -> the graph's edges
- `lineage.get_nodes()` -> the graph's nodes
- `lineage.get_paths()` -> all complete paths in the graph (from root to leaf)
- `lineage.get_queries()` -> all SQL queries
- `lineage.graph` -> the graph storing all the lineage (type = `networkx.classes.multidigraph.MultiDiGraph`)
- `lineage.print_tree()`
- `lineage.print_paths()`
```
column[source.name] -> function[LOWER()] -> column[target.name]
literal[5] -> column[target.age]
function[CURRENTTIMESTAMP()] -> column[target.birthday]
```
- `lineage.print_json()`
```
{
  "nodes": [
    {
      "id": "node:5636ee40c3b0eb15",
      "full_name": "column[fruit.processed.name type=VARCHAR kind=table]",
      "catalog": "",
      "schema": "fruit",
      "table": "processed",
      "column": "name",
      "data_type": "VARCHAR",
      "kind": "column",
      "table_type": "table",
      "table_properties": []
    },
    {
      "id": "node:02bb8f43ae05e57c",
      "full_name": "column[fruit.raw.name type=VARCHAR kind=table]",
      "catalog": "",
      "schema": "fruit",
      "table": "raw",
      "column": "name",
      "data_type": "VARCHAR",
      "kind": "column",
      "table_type": "table",
      "table_properties": []
    }
  ],
  "edges": [
    {
      "id": "edge:91fa8f96e1fd58b8",
      "parent": {
        "id": "node:02bb8f43ae05e57c",
        "full_name": "column[fruit.raw.name type=VARCHAR kind=table]"
      },
      "child": {
        "id": "node:5636ee40c3b0eb15",
        "full_name": "column[fruit.processed.name type=VARCHAR kind=table]"
      },
      "query": {
        "id": "query:91380b543ff563bd"
      }
    }
  ],
  "queries": [
    {
      "id": "query:91380b543ff563bd",
      "kind": "insert",
      "index": -1,
      "text_original": "INSERT INTO fruit.processed SELECT raw.name AS name FROM fruit.raw AS raw",
      "text_length": 73,
      "text_sha256_hash": "04de304a8a7e9827d980cc49104f6901",
      "stored_procedure": {}
    }
  ],
  "paths": [
    {
      "id": "path:90724054869db765",
      "length": 1,
      "hops": [
        "edge:91fa8f96e1fd58b8"
      ]
    }
  ]
}
```

# Roadmap
Future features:
- validation/error detection of SQL queries uniquely determined by the lineage
- querying ordering awareness
- dependency order resolution of CREATE statements

The following types of queries and nodes need to be created.

### Postgres
- XML
- File

- CREATE TABLE
  - LIKE
  - INHERITS
  - Generated columns
  - Default columns
  - EXTERNAL
  - FOREIGN

- SELECT
  - LATERAL
  - ROWS FROM
  - FROM ONLY
  - WITH (INSERT ...) AS
  - WITH ORDINALITY
  - WINDOW

- CREATE FUNCTION
  - CALLED ON NULL INPUT
  - RETURNS NULL ON NULL INPUT
  - RETURNS TABLE
  - RETURNS <expression>
  - Heredoc extraction
  - Inner statement parsing
  - Function parameters (IN, OUT, INOUT)

- CREATE TRIGGER
  - Implement behaviour

- INSERT
  - RETURNING
  - ON CONFLICT DO UPDATE
  - VALUES
  - OVERRIDING {SYSTEM|USER} VALUE

- COPY FROM/TO

### Redshift
- CREATE TABLE
  - EXTERNAL

- UNLOAD

### Snowflake
- CREATE STAGE
- CREATE PIPE
- CREATE TASK
- CREATE TABLE
  - HYBRID
- PUT
- GET
