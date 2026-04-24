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
- [ ] Hidden (system) columns
  - [x] TABLE
  - [x] CTAS
  - [ ] MATERIALIZED VIEW
- [ ] System tables (pg_class, pg_attribute)

CREATE TABLE
  - [x] AS
  - [x] LIKE
    - [x] INCLUDING
    - [x] EXCLUDING
  - [x] INHERITS
  - [ ] FOREIGN
    - not supported by sqlglot
    - Include 'tableoid' system column
  - [x] Generated columns
  - [ ] Identity columns
    - [ ] Sequence node
  - [x] Default columns
  - [ ] OF <type>
    - not supported by sqlglot

CREATE VIEW
  - [x] Regular
  - [x] MATERIALIZED
  - [ ] TEMPORARY
  - [ ] RECURSIVE

CREATE SEQUENCE
- [x] Include functions

CREATE RULE

SELECT
  - [x] System functions
    - [x] JSON functions
      - [ ] Hard-code default returned column names
  - [x] Window functions
  - [ ] FROM udf()
  - [x] UNION
  - [x] EXCEPT
  - [x] INTERSECT
  - [x] CTEs
    - [x] Regular
    - [x] RECURSIVE
    - [o] WITH (INSERT)
    - [x] WITH (UPDATE)
    - [x] WITH (MERGE)
    - [ ] WITH (VALUES)
  - [ ] LATERAL
    - sqlglot optimize() creates weird output
  - [ ] ROWS FROM
    - [x] Aliases
    - [ ] No aliases
    - [ ] LATERAL ROWS FROM
      - Not supported by sqlglot
  - [x] INTO
  - [x] FROM ONLY
  - [ ] WITH ORDINALITY
  - [ ] WINDOW
  - [x] SELECT FROM ( VALUES ())

MERGE
- [x] Regular
- [x] RETURNING + merge_action()

UPDATE
- [x] Regular
- [x] RETURNING

DELETE
- [ ] RETURNING

INSERT
  - [x] DEFAULT VALUES
  - [x] RETURNING
  - [ ] ON CONFLICT DO UPDATE
  - [x] VALUES
    - [x] (DEFAULT, DEFAULT)
    - [x] Multi-row
  - [ ] OVERRIDING {SYSTEM|USER} VALUE
    - not supported by sqlglot
  - [ ] INTO VIEW (automatically updatable views)
  - [x] CTEs with INSERT, UPDATE, etc, as above with SELECT

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
- not supported by sqlglot

EXECUTE
- not supported by sqlglot

CREATE TRIGGER
  - [ ] INSTEAD OF
  - [ ] BEFORE / AFTER

CREATE TYPE
- not supported by sqlglot

- COPY 
  - [ ] FROM
  - [ ] TO

DO
- not supported by sqlglot


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
