# sqlleaf
Extract detailed lineage from any SQL statement.

#### This is currently under early development and is not yet 0.0.1. Expect breaking changes!

See `ROADMAP.md` for supported syntax and upcoming features.

## Example

```python
sql = """
CREATE TABLE target (name VARCHAR, age INT, birthday TIMESTAMP);
CREATE TABLE source (name VARCHAR);

INSERT INTO target (name, age, birthday)
SELECT LOWER(name) AS name, 5 as age, CURRENT_TIMESTAMP as birthday
FROM source;
"""
import sqlleaf
lineage = sqlleaf.Lineage()
lineage.generate(sql=sql, dialect="postgres")
lineage.print_paths()
```
Output:
```
column[source.name] -> function[LOWER] -> column[target.name]
literal[5] -> column[target.age]
function[CURRENT_TIMESTAMP] -> column[target.birthday]
```
