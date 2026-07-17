# sqlleaf
### Trace your data
sqlleaf analyses your SQL statements to understand how your data flows across your data systems.
It never runs your queries; it only looks at their structure and syntax.

For the full roadmap and types of queries that are supported, visit https://sqlleaf.io

## Development
The project uses the `sqlglot` multi-dialect SQL parser under the hood, which supports over 30 SQL dialects. sqlleaf thus inherits this capability.
However, as sqlleaf is only young, it does not yet support all the features of every dialect. Only Postgres is supported as of now, and more dialects are coming!

## Example

```sql
-- File: example.sql
CREATE TABLE users (name VARCHAR(50), birthday DATE);
CREATE TABLE logins (name VARCHAR(50));

INSERT INTO users (name, birthday)
SELECT LOWER(name) AS name, CURRENT_TIMESTAMP AS birthday
FROM logins;
```

```python
sql = open("example.sql").read()

import sqlleaf
lineage = sqlleaf.Lineage()
lineage.generate(sql=sql, dialect="postgres")
lineage.print_paths()
```
Output:
```
column[logins.name] -> function[LOWER] -> column[users.name]
function[CURRENT_TIMESTAMP] -> column[users.birthday]
```
