# Project Overview
`sqlleaf` is a specialized SQL lineage extraction engine that provides granular, column-level data flow analysis between SQL expressions. It distinguishes itself from traditional lineage tools by explicitly modeling transformations—treating functions, literals, variables, and window functions as distinct nodes in a directed graph representation, rather than just tracking simple table-to-table transitions. By leveraging `networkx` for its internal graph structure, `sqlleaf` enables precise reconstruction of data movements and transformations across complex SQL pipelines, including support for stored procedures, UDFs, and various database-specific dialects.

# Project Map & Context
```text
sqlleaf/
├── __init__.py          # Package entry point, exposing the main Lineage API and core processing functions
├── exception.py         # Custom exception classes for the project
├── lineage.py           # Primary API for generating and managing SQL lineage graphs
├── mappings.py          # Object name resolution and mapping between SQL entities
├── path.py              # Algorithms for graph traversal and lineage path discovery
├── typing.py            # Common type hints and enumerations
├── dialects/            # Custom parsers for SQL dialects
│   └── plpgsql/         # A parser for the PL/pgSQL procedural dialect in Postgres (tokenizer, parser, generator, dialect, classes)
├── models/              # Data models and state containers
│   ├── context.py       # GeneratorContext and PositionContext for AST traversal
│   ├── hook.py          # Hooks for injecting custom behavior into the processing pipeline
│   ├── node/            # Definitions for graph nodes and edges
│   └── query/           # Definitions for different categories of SQL queries
├── processors/          # Main analysis and generation engines
│   ├── collector/       # Object discovery and extraction from SQL AST
│   │   ├── collector.py # Entry point: collect_queries()
│   │   └── classify.py  # Query-type classification logic
│   ├── generator/       # Graph construction engine
│   │   ├── generator.py # Entry point + walker functions (generate_lineage_for_query, walk_*)
│   │   └── dialects/    # Dialect-specific generator overrides
│   │       ├── base.py
│   │       ├── postgres.py
│   │       ├── mysql.py
│   │       ├── redshift.py
│   │       ├── snowflake.py
│   │       └── athena.py
│   ├── transformer/     # AST normalization and simplification
│   │   ├── transformer.py       # Entry point: transform_query()
│   │   ├── insert.py, update.py, merge.py, delete.py, ctas.py, copy.py, ...  # Per-query-type transformer modules
│   │   └── expressions/ # Expression-level transformations
│   │       ├── values.py
│   │       ├── row.py
│   │       ├── format.py
│   │       └── functional_notation.py
│   └── substitutor/     # Parameter/placeholder substitution logic
│       └── substitute.py
├── settings/            # Dialect-specific configuration and behavior settings
│   ├── base.py
│   ├── postgres.py
│   └── athena.py
└── util/                # Core utility functions
    ├── expression.py    # SQL expression manipulation utilities
    ├── graph.py         # networkx graph operations
    ├── helpers.py       # General purpose helper functions
    └── iterators.py     # Custom iterators for traversing SQL expressions
```

See the `README.md` in the root of this repository for additional context and examples.

# Core Architecture: Collector → Transformer → Generator
The lineage extraction process follows a strictly sequential pipeline where each stage refines the SQL representation until it can be deterministically mapped to a graph.

## 1. Collector
The **Collector** is the discovery phase. It parses raw SQL strings into a structured Abstract Syntax Tree (AST) and categorizes them into high-level query objects.

- **Primary Role:** Object discovery and query categorization.
- **Entry Point:** `sqlleaf.processors.collector.collect_queries()`
- **Key Operations:**
    - **Parsing:** Uses `sqlglot` to generate an initial AST for one or more SQL statements.
    - **Classification:** Maps AST nodes to specialized `Query` types (e.g., `InsertQuery`, `UpdateQuery`, `MergeQuery`) defined in `sqlleaf.models.query`.
    - **State Initialization:** Populates `ObjectMapping` to track table schemas and CTE definitions that will be needed for identifier resolution.
    - **Normalization:** Performs initial identifier normalization (casing, quoting) based on the target dialect.

## 2. Transformer
The **Transformer** is the normalization phase. It modifies the AST to simplify complex SQL patterns into a uniform structure that is easier to analyze.

- **Primary Role:** AST normalization and simplification.
- **Entry Point:** `sqlleaf.processors.transformer.transform_query()`
- **Key Operations:**
    - **DML Flattening:** Converts complex DML like `UPDATE`, `MERGE`, or `COPY` into equivalent `INSERT .. SELECT` structures to model data movement consistently.
    - **Clause Stripping:** Removes clauses that do not contribute to column-level lineage, such as `WHERE`, `ORDER BY`, and `GROUP BY`.
    - **Qualification:** Uses `sqlglot`'s optimizer to fully qualify all table and column identifiers, ensuring there is no ambiguity during graph construction.
    - **Expansion:** Expands `VALUES` clauses into `SELECT` unions and handles writable CTEs by linking their outputs to the dependent queries.

## 3. Generator
The **Generator** is the construction phase. It recursively traverses the normalized AST to build the final directed graph representing the lineage.

- **Primary Role:** Graph construction and data flow mapping.
- **Entry Point:** `sqlleaf.processors.generator.generate_lineage_for_query()`
- **Key Operations:**
    - **Scope Resolution:** Leverages `sqlglot`'s `Scope` objects to correctly resolve column references across nested subqueries and CTEs.
    - **Recursive Walking:** Starting from the target columns, it walks backwards through the expression tree to identify all source nodes (Columns, Literals, Functions).
    - **Node Modeling:** Creates distinct `Node` for every transformation step—treating functions and variables as first-class nodes rather than just labels on edges.
    - **Graph Assembly:** Connects nodes in a `networkx.MultiDiGraph`, preserving the exact sequence of transformations and data origins.

There are several execution paths that are taken during lineage generation according to their syntax:
- The queries that can be converted into `INSERT..SELECT` move through `generate_lineage_for_columns()`. This is almost every query type.
- The queries that cannot are either processed as-is and short-circuited in `generate_lineage_for_query()` (e.g. `PUT`, `CREATE EXTERNAL TABLE`)

### Walker methods
(1) `walk_query_and_build_graph()`: traverses the whole SQL expression 'downward' into nested queries (e.g. CTEs, subqueries, UNIONs)
(2) `walk_expressions_and_build_graph()`: traverses an SQL expression at a given depth in the tree (e.g. inside a single subquery)

Method (1) calls (2) for each expression level ("Scope") it yields before it traverses into the next Scope.

# General guidance
Tools to help with coding and troubleshooting while using `sqglot`:

## Convert an expression to SQL
`expression.sql(dialect="postgres")`

## Check if an expression is valid SQL
Run the command:
`sqlglot.parse_one("SELECT 1 + 1" dialect="postgres")`
throws `sqlglot.errors.ParseError` if there are syntax errors.

## AST and expression traversal
This is one of the most important points.

All SQL expressions are represented using subclasses of `expr.Expr` and share common properties that can be used for exploration.
They information about the expression itself and its parent & child expressions.
More information can be found in `context/ast_primer.md`.

## Functions to process and produce expressions
Prefer sqlglot's functions rather than building your own functions when handling expressions.
Expressions are defined as any class inside `sqlglot.exp` or a subclass of `exp.Expr`.

Example access functions:
- expr.unalias() - access a column inside `Alias(Column)`
- expr.unnest() - access an expression inside `Subquery(Expr)` or `Paren(Expr)`
- expr.unwrap() - access a query inside a Subquery

Example expression builder functions:
- expr.select() - builds a `SELECT` statement
- expr.insert() - builds an `INSERT` statement
- expr.subquery() - builds a `SELECT (...)` statement 

Example iteration functions:
- expr.find_ancestor(*Expr) - find ancestors of one or more expression types
- expr.find(*Expr) - find one descendent of one or more expression types
- expr.find_all(*Expr) - find all descendents of one or more expression types
- expr.walk() - walks every expression in the tree

Each sqlglot Query subclass also has useful methods to access internal structures:
- exp.Subquery() has `unnest()`, `unwrap()`, `is_wrapper`, etc

You can print the sqlglot AST using `repr()` to get an understanding of how to walk it, as it displays all the expressions and their attributes.

# Testing
The tests are found under directory `tests/`. 
When testing a file or directory, ensure the output of each test is suppressed, with only the result being shown (i.e. `-q`).
When testing individual tests, include the full output log in the result via the flag `-vvv`. Don't include `-q` with `-vvv`.

# Other
- Use the directory `scratch` for creating any files or test scripts that you may need.
- If you ever add or remove a file, make sure you update the directory map at the top of this file.
- Never try to lint or format the code after you make a change.
- Do not write code that is overly defensive.
- If you need to debug code, follow the rules for searching the log:
  - If it's for the transformer, search the log between "---- Transformer ----" and "---- Transformer End ----"
  - If it's for the transformer, search the log between "---- Generator ----" and "---- Generator End ----"
