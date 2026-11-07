import re
from functools import cache
from pathlib import Path

TABLE_HEADER = re.compile(r"^CREATE TABLE (\w+)\.(\w+) \(", re.MULTILINE)
STATEMENT_END = "\n);"


@cache
def _read(dialect: str) -> tuple[str, dict[tuple[str, str], tuple[int, int]]]:
    path = Path(__file__).parent / dialect / "system_objects" / f"{dialect}.sql"
    if not path.exists():
        return "", {}

    text = path.read_text()
    index = {}
    for match in TABLE_HEADER.finditer(text):
        end = text.index(STATEMENT_END, match.start()) + len(STATEMENT_END)
        index[(match.group(1).lower(), match.group(2).lower())] = (match.start(), end)
    return text, index


def get_object_ddl(dialect: str, schema: str, table: str) -> str | None:
    text, index = _read(dialect)
    span = index.get((schema.lower(), table.lower()))
    if span is None:
        return None
    return text[span[0] : span[1]]
