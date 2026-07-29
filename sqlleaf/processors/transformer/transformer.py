import logging

from sqlglot import exp

from sqlleaf import mappings, util
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
from sqlleaf.processors.transformer import (
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


def transform_query(holder: QueryHolder) -> None:
    """
    1. Transform the original query's AST (DML flattening, qualification, etc.).
    2. If the original query contains UDF call sites, replace each call with an
       inline subquery built from the output columns of the last transformed
       downstream holder for that call — producing `holder.transformed`.
    """
    transformed_query = _transform_query_instance(query=holder.original)
    holder.set_transformed_query(query=transformed_query)


def _transform_query_instance(query: Q) -> Q:
    """
    Helper to transform a Query instance.
    """
    statement_to_transform = util.copy_expression(query.statement)
    transformed_statement = _transform_statement(statement=statement_to_transform, query=query)

    return _build_transformed_query(
        original_query=query,
        transformed_statement=transformed_statement,
    )


def _build_transformed_query(
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
            skip_annotate=True,
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
    logger.debug("---- Transformer ---")
    logger.debug(f"Query: {statement.sql(dialect=query.dialect)}")
    logger.debug(f"Transforming: {query.__class__.__name__} - {statement.__class__}")

    transformer_cls = _TRANSFORMER_MAP.get(type(query), BaseQueryTransformer)
    transformer = transformer_cls(statement, query)
    stmt = transformer.preprocess(statement)
    logger.debug(f"[Transformer] After pre-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.transform(stmt)
    logger.debug(f"[Transformer] After process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.postprocess(stmt)
    logger.debug(f"[Transformer] After post-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    return stmt
