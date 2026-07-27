import logging
import typing as t

from sqlglot import exp

from sqlleaf import mappings, typing, util
from sqlleaf.models.query import (
    CallQuery,
    CopyQuery,
    CTASQuery,
    DeleteQuery,
    ExecuteQuery,
    InsertQuery,
    MergeQuery,
    MultitableInsertQuery,
    Q,
    QueryHolder,
    ReplaceQuery,
    TableQuery,
    UnloadQuery,
    UpdateQuery,
    ValuesQuery,
)
from sqlleaf.processors import collector as _collector
from sqlleaf.processors.transformers import (
    BaseQueryTransformer,
    CallTransformer,
    CopyTransformer,
    CTASTransformer,
    DeleteTransformer,
    ExecuteTransformer,
    InsertTransformer,
    MergeTransformer,
    MultitableInsertTransformer,
    ReplaceTransformer,
    UnloadTransformer,
    UpdateTransformer,
    ValuesTransformer,
    udf,
)
from sqlleaf.typing import E

_TRANSFORMER_MAP: dict[type, type[BaseQueryTransformer]] = {
    CallQuery: CallTransformer,
    CTASQuery: CTASTransformer,
    CopyQuery: CopyTransformer,
    DeleteQuery: DeleteTransformer,
    ExecuteQuery: ExecuteTransformer,
    InsertQuery: InsertTransformer,
    MergeQuery: MergeTransformer,
    MultitableInsertQuery: MultitableInsertTransformer,
    ReplaceQuery: ReplaceTransformer,
    TableQuery: BaseQueryTransformer,  # pass-through
    UnloadQuery: UnloadTransformer,
    UpdateQuery: UpdateTransformer,
    ValuesQuery: ValuesTransformer,
}

logger = logging.getLogger("sqlleaf")

"""
Transform an SQL query into a single canonical form that we can easily generate the lineage from.
The form is `INSERT .. SELECT`.
"""

# TODO: ensure columns have valid types after all transformations (only top-level SELECT for now)


def transform_query(
    holder: QueryHolder,
    dialect: str,
    object_mapping: mappings.ObjectMapping,
) -> None:
    """Phase 2 entry point: apply substitution (if applicable), then transform."""
    # Step 1: substitution — discover inner statements and populate holder.substituted
    _apply_substitution(holder, dialect, object_mapping)

    # Step 2: transform original
    transformed_query = _transform_query_instance(holder.original)
    holder.set_transformed_query(transformed_query)

    # Step 3: transform substituted (if present)
    if holder.substituted:
        transformed_substituted = [_transform_query_instance(q) for q in holder.substituted]
        holder.set_substituted_queries(transformed_substituted)


def _apply_substitution(
    holder: QueryHolder,
    dialect: str,
    object_mapping: mappings.ObjectMapping,
) -> None:
    """
    Perform substitution for UDF calls, procedures, and prepared statements.
    If substitutions are found, create a substituted query and collect its children.
    """
    if holder.substituted:  # non-empty list means already substituted
        return

    original_query = holder.original
    statement = util.copy_expression(original_query.statement)

    subst_statements: t.List[exp.Expr] = []
    if isinstance(original_query, CallQuery):
        subst_statements = udf.substitute_call(query=original_query)
    elif isinstance(original_query, ExecuteQuery):
        subst_statements = udf.substitute_execute(query=original_query)
    elif (
        isinstance(original_query, CTASQuery)
        and original_query.source_info.type == typing.SqlObjectType.PREPARED_STATEMENT
    ):
        subst_statements = [udf.substitute_create_execute(query=original_query)]
    else:
        subst_statements = udf.substitute_udf(statement=statement, query=original_query)

    if subst_statements:
        for i, stmt in enumerate(subst_statements):
            # The substituted query is a NEW query, so we must classify it correctly.
            # Use original query's index as a base.
            substituted_query = _collector._process_unnamed(
                statement=stmt,
                dialect=dialect,
                object_mapping=object_mapping,
                statement_index=original_query.statement_index,
            )
            if substituted_query:
                holder.add_substituted_query(substituted_query)


def _transform_query_instance(query: Q) -> Q:
    """
    Helper to transform a Query instance.
    """
    statement_to_transform = util.copy_expression(query.statement)
    transformed_statement = _transform_statement(statement_to_transform, query)

    return build_transformed_query(
        original_query=query,
        transformed_statement=transformed_statement,
    )


def build_transformed_query(
    original_query: Q,
    transformed_statement: exp.Expr,
) -> Q:
    """
    Create a new Query instance whose statement is the transformed expression.
    The Query subclass is selected based on the statement type.
    """
    if isinstance(transformed_statement, exp.Insert):
        new_query = InsertQuery(
            expr=transformed_statement,
            dialect=original_query.dialect,
            object_mapping=original_query.object_mapping,
            statement_index=original_query.statement_index,
        )
        # TODO: everything below this in this function this should not occur
        #  - requires big refactor
        # CopyQuery special case: preserve source_info/target_info so that
        # _apply_optimizations can still read the STREAM/FILE/STAGE type.
        if isinstance(original_query, (CopyQuery, UnloadQuery)):
            new_query.source_info = original_query.source_info
            new_query.target_info = original_query.target_info
    else:
        # For statements not converted to INSERT, keep the same Query subclass
        # but with the new statement.
        new_query = original_query.__class__.__new__(original_query.__class__)
        new_query.__dict__.update(original_query.__dict__)
        new_query.statement = transformed_statement

    # Propagate shared metadata
    new_query.column_defs = original_query.column_defs
    new_query.parent_query = original_query.parent_query
    # Store a reference to the original query so that type-based checks in the
    # generator (e.g. isinstance(query, UpdateQuery)) can inspect the original class.
    new_query.original_query = original_query
    return new_query


def _transform_statement(statement: E, query: Q) -> exp.Expr:
    """
    Perform a series of transformations against an SQL statement.
    Dispatches to the appropriate transformer class based on the query type.
    """
    logger.debug("----")
    logger.debug(f"Query: {statement.sql(dialect=query.dialect)}")
    logger.debug(f"Transforming: {query.__class__.__name__} - {statement.__class__}")

    transformer_cls = _TRANSFORMER_MAP.get(type(query), BaseQueryTransformer)
    transformer = transformer_cls(statement, query)
    transformer.preprocess()
    logger.debug(f"[Transformer] After pre-process: {statement.sql(dialect=query.dialect)}")
    transformer.transform()
    logger.debug(f"[Transformer] After process: {statement.sql(dialect=query.dialect)}")
    stmt = transformer.postprocess()
    logger.debug(f"[Transformer] After post-process: {stmt.sql(dialect=query.dialect)}")
    return stmt
