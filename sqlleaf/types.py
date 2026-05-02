from __future__ import annotations
import logging
import typing as t

import networkx as nx
if t.TYPE_CHECKING:
    pass

from sqlleaf.objects.node_types import NodeAttributes


logger = logging.getLogger("sqlleaf")

def are_types_compatible(subtyp: str, typ: str, dialect: str) -> bool:
    """
    Check if two types are compatible. Type `subtyp` must be equal or less than `typ`.
    For example, SMALLINT is compatible with BIGINT, but not vice versa.
    """
    logger.info(f"Checking type compatibility between type '{typ}' and subtype '{subtyp}'")

    compatibility_matrix = {
        "postgres": {},
    }
    # TODO: add warnings to global tracker
    types = compatibility_matrix[dialect]
    if typ != subtyp and typ not in types[subtyp]:
        print(f"Warning: type {subtyp} is not compatible with {typ}")
        return False
    return True


def update_column_data_types(graph: nx.MultiDiGraph):
    """
    Update the column types of the nodes in the graph.

    Traverse each edge from the roots and:
    - Update the target column if its type is UNKNOWN by looking at the source column and its functions
    - Check if the source->target type conversion is compatible

    This is important for resolving column types of views, as multiple queries may have connected multiple views together whose
    types are by default UNKNOWN and therefore need resolution.
    """
    # TODO: Use sqlglot.expressions.DataType.is_type() as a first check
    logger.debug("Skipping data types as it's faulty")
    return


def ensure_correct_data_types(
    parent_attrs: NodeAttributes,
    child_attrs: NodeAttributes,
    last_function_type: str,
    dialect: str,
):
    """
    Check if the child column's type is compatible with its parent type or its outermost function's type.
    If we can determine the correct type for a child column, set it.
    Throw warnings if the types are incompatible.

    For example given,
        SELECT COUNT(LOWER(kind)) as cnt FROM fruit.raw;
    with columns:
        fruit.raw.kind => VARCHAR (from table)
        LOWER() => VARCHAR
        COUNT() => BIGINT
        cnt => INT (from table)
    We expect 'cnt' to be compatible with the outermost function (COUNT).
    """
    p_type = parent_attrs.data_type
    c_type = child_attrs.data_type
    logger.info(f"Checking type compatibility. Parent: {p_type}, Child: {c_type}, Last Function: {last_function_type}")

    # The last function takes precedence over the parent
    if last_function_type:
        if last_function_type == "UNKNOWN" and c_type == "UNKNOWN":
            # Do nothing
            pass
        elif last_function_type == "UNKNOWN" and c_type != "UNKNOWN":
            # Do nothing
            pass
        elif last_function_type != "UNKNOWN" and c_type == "UNKNOWN":
            # Set c_type <= last_function_type. This is key for resolving view types
            child_attrs.data_type = last_function_type
        elif last_function_type != "UNKNOWN" and c_type != "UNKNOWN":
            # Check if compatible
            are_types_compatible(subtyp=last_function_type, typ=c_type, dialect=dialect)
    else:
        # The child's type must be compatible with the parent's type
        if p_type == "UNKNOWN" and c_type == "UNKNOWN":
            # Do nothing
            pass
        elif p_type == "UNKNOWN" and c_type != "UNKNOWN":
            # Set p_type <= c_type. This is key for resolving view types
            parent_attrs.data_type = c_type
        elif p_type != "UNKNOWN" and c_type == "UNKNOWN":
            # Set p_type => c_type. This is key for resolving view types
            child_attrs.data_type = p_type
        elif p_type != "UNKNOWN" and c_type != "UNKNOWN":
            # Check if compatible
            are_types_compatible(subtyp=p_type, typ=c_type, dialect=dialect)

    p_type = parent_attrs.data_type
    c_type = child_attrs.data_type
    logger.info(f"New types. Parent: {p_type} Child: {c_type}")
