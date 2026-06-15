import hashlib
import typing as t


def unique(sequence: t.List):
    """
    Return a list of unique elements in a list while preserving insertion order.
    """
    seen = set()
    return [x for x in sequence if not (x in seen or seen.add(x))]


def flatten(lst: t.List):
    """
    Flatten a potentially nested list into a single list.
    For example,
        [a, 1, [b, c]]
    returns
        [a, 1, b, c]
    """
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def chunks(lst, n):
    """
    Yield successive n-sized chunks from lst.
    """
    return [lst[i : i + n] for i in range(0, len(lst), n)]


def short_sha256_hash(text: str):
    return hashlib.md5(text.encode()).hexdigest()[:16]


def long_sha256_hash(text: str):
    return hashlib.md5(text.encode()).hexdigest()
