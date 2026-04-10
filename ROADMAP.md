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
- [ ] XML
- [ ] File

CREATE TABLE
  - [ ] AS
  - [ ] LIKE
  - [ ] INHERITS
  - [ ] EXTERNAL
  - [ ] FOREIGN
  - [ ] Generated columns
  - [ ] Identity columns
  - [ ] Default columns
  - [ ] OF <type>

CREATE VIEW
  - [ ] Regular
  - [ ] MATERIALIZED
  - [ ] TEMPORARY

CREATE SEQUENCE
- [ ] Include functions

SELECT
  - [ ] System functions
    - [ ] JSON functions
      - [ ] Hard-code default returned column names
  - [ ] Window functions
  - [ ] FROM udf()
  - [ ] UNION
  - [ ] CTEs
    - [ ] Regular
    - [ ] RECURSIVE
    - [ ] WITH (INSERT)
    - [ ] WITH (UPDATE)
    - [ ] WITH (MERGE)
    - [ ] WITH (VALUES)
  - [ ] LATERAL
    - sqlglot optimize() creates weird output
  - [ ] ROWS FROM
    - [ ] Aliases
    - [ ] No aliases
    - [ ] LATERAL ROWS FROM
      - Not supported by sqlglot
  - [ ] INTO
  - [ ] FROM ONLY
  - [ ] WITH ORDINALITY
  - [ ] WINDOW
  - [ ] SELECT FROM ( VALUES ())

MERGE

UPDATE

INSERT
  - [ ] RETURNING
  - [ ] ON CONFLICT DO UPDATE
  - [ ] VALUES
  - [ ] OVERRIDING {SYSTEM|USER} VALUE
  - [ ] INTO VIEW (automatically updatable views)

CREATE FUNCTION (language SQL)
  - [ ] CALLED ON NULL INPUT
  - [ ] RETURNS NULL ON NULL INPUT
  - [ ] RETURNS TABLE
  - [ ] RETURNS <expression>
  - [ ] Heredoc extraction
  - [ ] Inner statement parsing
  - [ ] Function parameters (IN, OUT, INOUT)

CREATE PROCEDURE (language SQL)

PREPARE

EXECUTE

CREATE TRIGGER
  - [ ] INSTEAD OF
  - [ ] BEFORE / AFTER

CREATE TYPE

- COPY 
  - [ ] FROM
  - [ ] TO

DO


### Redshift
CREATE TABLE
  - [ ] EXTERNAL

SELECT
  - [ ] PIVOT
  - [ ] UNPIVOT

INSERT
  - [ ] Multi-row

- [ ] UNLOAD

### Snowflake
- CREATE STAGE
- CREATE PIPE
- CREATE TASK
- CREATE SEMANTIC VIEW
- CREATE TABLE
  - [ ] EXTERNAL
  - [ ] HYBRID
  - [ ] DYNAMIC
  - [ ] USING TEMPLATE
  - [ ] CLONE
  - [ ] FROM ARCHIVE OF
  - [ ] FROM BACKUP OF
  - [ ] AS SELECT
- [ ] TO_QUERY
- [ ] UDTF (user defined table function)
- [ ] COPY FILES
- [ ] PUT
- [ ] GET
- [ ] Multi-table INSERT
