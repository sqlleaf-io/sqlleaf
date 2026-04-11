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
  - [x] AS
  - [x] LIKE [wip]
    - [x] INCLUDING
    - [x] EXCLUDING
  - [ ] INHERITS
  - [ ] EXTERNAL
  - [ ] FOREIGN
  - [x] Generated columns
  - [ ] Identity columns
  - [x] Default columns
  - [ ] OF <type>

CREATE VIEW
  - [x] Regular
  - [x] MATERIALIZED
  - [ ] TEMPORARY

CREATE SEQUENCE
- [x] Include functions

SELECT
  - [x] System functions
    - [x] JSON functions
      - [ ] Hard-code default returned column names
  - [x] Window functions
  - [ ] FROM udf()
  - [ ] UNION
  - [x] CTEs
    - [x] Regular
    - [x] RECURSIVE
    - [ ] WITH (INSERT)
    - [ ] WITH (UPDATE)
    - [ ] WITH (MERGE)
    - [ ] WITH (VALUES)
  - [ ] LATERAL
    - sqlglot optimize() creates weird output
  - [ ] ROWS FROM
    - [x] Aliases
    - [ ] No aliases
    - [ ] LATERAL ROWS FROM
      - Not supported by sqlglot
  - [x] INTO
  - [ ] FROM ONLY
  - [ ] WITH ORDINALITY
  - [ ] WINDOW
  - [ ] SELECT FROM ( VALUES ())

MERGE
- [x] Regular

UPDATE
- [x] Regular

INSERT
  - [ ] RETURNING
  - [ ] ON CONFLICT DO UPDATE
  - [x] VALUES
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
