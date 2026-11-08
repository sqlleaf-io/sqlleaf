import re
from functools import cache
from pathlib import Path

TABLE_HEADER = re.compile(r"^CREATE TABLE (\w+)\.(\w+) \(", re.MULTILINE)
VIEW_HEADER = re.compile(r"^CREATE VIEW (\w+)\.(\w+) AS", re.MULTILINE)
SCHEMA_HEADER = re.compile(r"^CREATE SCHEMA (\w+);", re.MULTILINE)

KINDS = {
    "tables": (TABLE_HEADER, "\n);"),
    "views": (VIEW_HEADER, ";\n"),
    "schemas": (SCHEMA_HEADER, ";\n"),
}


@cache
def _read_system_objects(dialect: str, kind: str) -> tuple[str, dict[tuple[str, ...], tuple[int, int]]]:
    """
    Read the system objects from disk.
    """
    path = Path(__file__).parent / dialect / "system_objects" / f"{kind}.sql"
    if not path.exists():
        return "", {}

    header, statement_end = KINDS[kind]
    text = path.read_text()
    if kind in ("tables", "views"):
        # sqlglot fails when parsing 'oid[]'
        text = text.replace("oid[]", "array<oid>")
    index = {}
    for match in header.finditer(text):
        end = text.index(statement_end, match.start()) + len(statement_end)
        index[tuple(group.lower() for group in match.groups())] = (match.start(), end)
    return text, index


def _lookup(dialect: str, kind: str, key: tuple[str, ...]) -> str | None:
    text, index = _read_system_objects(dialect, kind)
    span = index.get(key)
    if span is None:
        return None
    return text[span[0] : span[1]]


def get_object_ddl(schema: str, table: str, dialect: str) -> str | None:
    key = (schema.lower(), table.lower())
    return _lookup(dialect, "tables", key) or _lookup(dialect, "views", key)


def get_schema_ddl(schema: str, dialect: str) -> str | None:
    return _lookup(dialect, "schemas", (schema.lower(),))
