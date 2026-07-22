import typing as t

def default_column_index_iterator(dialect: str, elems: t.List[t.Any]) -> t.Generator[str]:
    """
    Generates default columns defined for a specific SQL dialect.
    """
    for i in range(len(elems)):
        if dialect == "postgres":
             yield f"column{i+1}"
        elif dialect == "mysql":
            yield f"column_{i}"
        else:
            yield f"column{i+1}"
