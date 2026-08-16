# sqlleaf
## Trace your data
sqlleaf is a tool to help you to understand how your data flows across your data systems by producing detailed, column-level lineage across any SQL query and dialect.

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

## Development
This project is under heavy development; version 0.1 will be released soon.
