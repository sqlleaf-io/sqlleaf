import logging
import typing as t

from sqlglot import exp

from sqlleaf import util
from sqlleaf.models.query import (
    CopyQuery,
    CTASQuery,
    DeleteQuery,
    InsertQuery,
    MergeQuery,
    Q,
    TableQuery,
    UnloadQuery,
    UpdateQuery,
    QueryHolder
)
from sqlleaf.processors.transformers import substitute, BaseQueryTransformer, InsertTransformer, CopyTransformer, DeleteTransformer, MergeTransformer, CTASTransformer, UnloadTransformer, UpdateTransformer

from sqlleaf.typing import E

_TRANSFORMER_MAP: dict[type, type[BaseQueryTransformer]] = {
    CTASQuery:    CTASTransformer,
    CopyQuery:    CopyTransformer,
    DeleteQuery:  DeleteTransformer,
    InsertQuery:  InsertTransformer,
    MergeQuery:   MergeTransformer,
    TableQuery:   BaseQueryTransformer,  # pass-through
    UnloadQuery:  UnloadTransformer,
    UpdateQuery:  UpdateTransformer,
}

logger = logging.getLogger("sqlleaf")

"""
Transform an SQL query into a single canonical form that we can easily generate the lineage from.
The form is `INSERT .. SELECT`.
"""

# TODO: ensure columns have valid types after all transformations (only top-level SELECT for now)


def transform_query(holder: QueryHolder) -> None:
    """
    Transform a query's expression according to rules specific to its type.
    Writes the results to holder.transformed and holder.substituted.
    """
    original_query = holder.original
    statement_to_transform = util.copy_expression(original_query.statement)

    transformed_statement = _transform_statement(statement_to_transform, original_query)

    transformed_query = _build_transformed_query(
        original_query=original_query,
        transformed_statement=transformed_statement,
    )
    holder.set_transformed_query(transformed_query)

    # Substitution
    statement_to_substitute = util.copy_expression(transformed_statement)
    subst_statements = _get_substituted_statements(statement_to_substitute, original_query)
    if subst_statements:
        # TODO: a list of transformed inner queries is returned, but right now
        #  we only care about the last statement. In an upcoming commit, process all
        #  the transformed statements separately.
        substituted_statement = subst_statements[-1]
        substituted_query = _build_transformed_query(
            original_query=original_query,
            transformed_statement=substituted_statement,
        )
        holder.set_substituted_query(substituted_query)


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


def _get_substituted_statements(statement: exp.Expr, query: Q) -> t.List[exp.Expr]:
    """
    Transform a statement by substituting all its UDF references with each UDF's underlying return expression.

    Returns a statement only if a UDF was substituted.
    """
    statements = substitute.substitute_udf(statement=statement, query=query)
    return statements


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
    transformer._preprocess()
    return transformer._postprocess(transformer.transform())
