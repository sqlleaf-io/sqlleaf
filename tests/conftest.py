import pytest


# @pytest.hookimpl(tryfirst=True)
# def pytest_assertrepr_compare(config, op, left, right):
#     """Bypasses PyCharm's 75-character terminal layout rules entirely."""
#     if op in ("==", "!="):
#         # Force an arbitrarily huge formatting width limit
#         # if isinstance(left, list):
#         #     flat_left = left
#         #     flat_right = right
#         # else:
#         flat_left = pprint.pformat(left, width=999, compact=True)
#         flat_right = pprint.pformat(right, width=999, compact=True)
#
#         return [
#             f"Assertion Failed ({op}):",
#             f"  Expected: {flat_left}",
#             f"  Actual:   {flat_right}"
#         ]


# conftest.py


@pytest.hookimpl(tryfirst=True)
def pytest_assertrepr_compare(op, left, right):
    """Formats the explanation text after a test has already failed."""
    if op in ("==", "!=") and isinstance(left, list) and isinstance(right, list):
        # Return a list of strings. Pytest will build a standard text diff out of these.
        explanation = []

        if not len(left) or isinstance(left[0], list):
            # We can't diff list-of-lists
            return

        if not len(right) or isinstance(right[0], list):
            # We can't diff list-of-lists
            return

        # We can dynamically use Python's difflib to show a neat line-by-line comparison
        import difflib
        diff = list(difflib.ndiff(right, left))
        explanation.extend(diff)

        if explanation:
            # Add a new line
            explanation.insert(0, "")
            explanation.append("")

        # diff_no_markers = ["["] + [line.removeprefix("+ ").removeprefix("- ") + "," for line in diff] + ["]"]

        # explanation.extend(diff_no_markers)

        # flat_left = pprint.pformat(left, width=999, compact=True)
        # flat_right = pprint.pformat(right, width=999, compact=True)
        # explanation.append("")
        # explanation.append(flat_left)
        # explanation.append(flat_right)

        if not right:
            # Print the list in a nice way for copying into tests
            diff_no_markers = ["["] + ["\t'" + line.removeprefix("+ ").removeprefix("- ") + "'," for line in diff] + ["]"]
            explanation.extend(diff_no_markers)

        return explanation
