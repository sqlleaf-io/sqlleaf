from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass, replace
from enum import StrEnum, auto

from sqlglot import exp
from sqlglot.expressions import ColumnDef

from sqlleaf.typing import SourceExprType, TargetExprType

if t.TYPE_CHECKING:
    pass

from sqlleaf import exception, mappings, util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.node_types import (
    ColumnNode,
    FileColumnNode,
    ProgramNode,
    StageColumnNode,
    StreamNode,
)
from sqlleaf.objects.query_types import CopyQuery, Q, TableQuery, UnloadQuery

logger = logging.getLogger("sqlleaf")

"""
A set of helper functions related involving complex methods.
"""

# TODO: this should be in node_types.py, but it's too big

TargetNodeType = ColumnNode | FileColumnNode | StageColumnNode | StreamNode | ProgramNode


# TODO: put this in every Node class?
@dataclass(frozen=True)
class TargetObject:
    type: TargetObjectType
    # This is not the *actual* target: it's just what was used to derive the columns,
    # as the source will need to act as the target if the target isn't a table.
    object: TargetExprType | SourceExprType
    columns: t.List[ColumnDef]


class TargetObjectType(StrEnum):
    """
    The types of objects that represent a 'target' in an SQL statement.
    """

    FILE = auto()
    PROGRAM = auto()
    STAGE = auto()
    STREAM = auto()
    TABLE = auto()


def iter_child_nodes(
    gen_ctx: GeneratorContext, pos_ctx: PositionContext
) -> t.Generator[t.Tuple[TargetNodeType | None, ColumnNode | None]]:
    """
    Iterate over every column of a table that was either selected in a query or has a default expression.
    """

    # Both COPY and UNLOAD can have SELECTs as their sources, which have arbitrary
    # columns that vary in length due to their sourcing from any table.
    object_mapping = gen_ctx.object_mapping
    query = gen_ctx.query
    expr = query.get_target()
    target_object = get_target_object_for_query(query, object_mapping)

    select_idx = 0

    # Iterate over every column and yield it if it is referenced in the query.
    for col_def in target_object.columns:
        selected_node = None
        default_node = None
        process_defaults = False
        gen_ctx = replace(gen_ctx, expr=col_def)
        pos_ctx = replace(pos_ctx, select_index=select_idx)

        match target_object.type:
            case TargetObjectType.FILE:
                file_format = util.get_file_format(expr.name)
                child_node = FileColumnNode(
                    column=col_def.name,
                    file_format=file_format,
                    file_path=expr.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case TargetObjectType.STAGE:
                child_node = StageColumnNode(
                    column=col_def.name,
                    stage=expr.this,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )
                process_defaults = True

            case TargetObjectType.TABLE:
                child_node = ColumnNode(
                    catalog=expr.catalog,
                    schema=expr.db,
                    table=expr.name,
                    column=col_def.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )
                process_defaults = True

            case TargetObjectType.STREAM:
                # Use the ColumnDef as the expr so that correct columns
                # are selected during walk()
                child_node = StreamNode(
                    name=expr.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case TargetObjectType.PROGRAM:
                # Use the ColumnDef as the expr so that correct columns
                # are selected during walk()
                child_node = ProgramNode(
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

        if col_def.name in query.get_selected_column_names() or isinstance(query, TableQuery):
            # Check if the column is selected.
            # A 'CREATE TABLE' has no SELECT, so include all columns if this case.
            selected_node = child_node

        if process_defaults and isinstance(child_node, ColumnNode) and child_node.get_column_constraint_expression():
            default_node = child_node
            # TODO: unset all index positions, set 'default=true' as position

        if selected_node or default_node:
            yield selected_node, default_node

        if selected_node:
            select_idx += 1


def get_target_object_for_query(query: Q, object_mapping: mappings.ObjectMapping) -> TargetObject:
    """
    Given a query, figure out its target object, including its columns.

    This is straightforward if source isn't a JOIN: we just use the source object's columns.
    But if it is a JOIN, we use the selected columns rather than the source's columns.
    """
    expr = query.get_target()

    if isinstance(expr, exp.Literal):
        # Use the parent table's columns as the child columns
        # Assumes this is a COPY | UNLOAD
        target_type = TargetObjectType.FILE
        target = query.get_source()

    elif isinstance(expr, exp.Identifier):
        target = query.get_source()

        if expr.name in ["stdin", "stdout"]:
            target_type = TargetObjectType.STREAM
        elif expr.name in ["program"]:
            target_type = TargetObjectType.PROGRAM
        else:
            raise exception.SqlLeafException(f"Unknown child column name in COPY: {expr.name}")

    elif isinstance(expr, exp.Table) and query.dialect == "snowflake":
        if isinstance(expr.this, exp.Var):
            target_type = TargetObjectType.STAGE
            # TODO: this assumes the source is a table!
            target = query.get_source()
        else:
            target_type = TargetObjectType.TABLE
            target = query.get_target()

    elif isinstance(expr, exp.Table):
        target_type = TargetObjectType.TABLE
        target = query.get_target_as_table()

    else:
        raise exception.SqlLeafException(f"Unknown child column type in COPY: {expr}")

    columns_from_object = _get_column_defs(target, query, object_mapping)

    return TargetObject(
        type=target_type,
        object=target,
        columns=columns_from_object,
    )


def _get_column_defs(
    target: SourceExprType | TargetExprType,
    query: Q,
    object_mapping: mappings.ObjectMapping,
) -> t.List[exp.ColumnDef]:
    """
    Most of the time, the sources and target are tables.
    However, with COPY/UNLOAD, they can be files or streams.

    If the target is not a table and the source is a SELECT,
    there may be a JOIN with many tables as the source.
    """
    if isinstance(query, (CopyQuery, UnloadQuery)):
        source = query.get_source()
        if isinstance(source, exp.Select):
            return [util.str_to_column_def(col) for col in source.named_selects]

    if not isinstance(target, exp.Table):
        return []

    table_query = object_mapping.get_table_or_stage(target)
    if not table_query:
        return []

    return table_query.get_column_defs()
