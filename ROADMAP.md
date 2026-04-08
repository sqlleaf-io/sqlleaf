# Roadmap
Future features:
- validation/error detection of SQL queries uniquely determined by the lineage
- querying ordering awareness
- dependency order resolution of CREATE statements
- Filtering:
```
lineage.filter(
    name,
    direction='',
    include_types=[],
    exclude_types=[],
    neighbors=0
)
```

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

- CREATE TYPE

- INSERT
  - RETURNING
  - ON CONFLICT DO UPDATE
  - VALUES
  - OVERRIDING {SYSTEM|USER} VALUE

- COPY 
  - FROM
  - TO


### Redshift
- CREATE TABLE
  - EXTERNAL

- Multi-row INSERT
- UNLOAD

### Snowflake
- CREATE STAGE
- CREATE PIPE
- CREATE TASK
- CREATE SEMANTIC VIEW
- CREATE TABLE
  - HYBRID
  - DYNAMIC
  - USING TEMPLATE
  - CLONE
  - FROM ARCHIVE OF
  - FROM BACKUP OF
  - AS SELECT
- TO_QUERY
- UDTF (user defined table function)
- COPY FILES
- PUT
- GET
- Multi-table INSERT
