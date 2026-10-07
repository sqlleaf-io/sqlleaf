import logging

from sqlglot import exp

from sqlleaf import util
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import (
    CopyQuery,
    AssignmentQuery,
    ExecuteDynamicQuery,
    FetchQuery,
    ForInQuery,
    InsertQuery,
    OpenQuery,
    Q,
    QueryHolder,
    SelectQuery,
    UnloadQuery,
)
from sqlleaf.processors.transformer import BaseQueryTransformer
from sqlleaf.typing import E


logger = logging.getLogger("sqlleaf")


def transform_query(query_holder: QueryHolder) -> None:
    """
    Transform an SQL query into a single, normalized form that we can easily generate lineage from.

    This runs a series of transformations specific to each query type. Queries register their own
    transformation functions to ensure that the query is fully qualified, with all columns added and
    functions substituted so that they can be extracted into a graph by the generator.
    """
    transformed_query = _transform_query_instance(query=query_holder.original)
    query_holder.set_transformed_query(query=transformed_query)
    # Set the variables here
    set_variables_in_scope(query=transformed_query)


def set_variables_in_scope(query: Q) -> None:
    """
    Set variables for this scope in the variable stack (VS).
    """
    if isinstance(query, AssignmentQuery):
        # `my_var := 42`
        name = query.get_key()
        value = query.get_value()
        query.object_mapping.set_variable(name=name, value=value)

    elif isinstance(query, OpenQuery):
        pass

    elif isinstance(query, SelectQuery):
        original_stmt = query.holder.original.statement
        original_parent = original_stmt.parent
        parent_holder = query.holder.parent_holder

        if isinstance(original_parent, pgexp.PGForIn) and original_parent.args["query"] == original_stmt:
            # `FOR .. IN SELECT ..`
            name = original_parent.this.name
            value = query.statement
            query.object_mapping.set_variable(name=name, value=value)

        elif (
            isinstance(original_parent, pgexp.PGOpen)
            and original_parent.args.get("expression") == original_stmt
        ):
            # `OPEN .. FOR SELECT ..`
            name = original_parent.this.name
            value = query.statement
            query.object_mapping.set_variable(name=name, value=value)

        elif parent_holder and isinstance(parent_holder.original, ExecuteDynamicQuery):
            # `FOR .. IN EXECUTE 'SELECT ..'`
            grandparent_holder = query.holder.parent_holder.parent_holder
            if grandparent_holder and isinstance(grandparent_holder.transformed, ForInQuery):
                for_in_stmt = grandparent_holder.transformed.statement
                name = for_in_stmt.this.name
                value = query.statement
                query.object_mapping.set_variable(name=name, value=value)
            elif grandparent_holder and isinstance(grandparent_holder.transformed, OpenQuery):
                # `OPEN .. FOR EXECUTE 'SELECT ..'`
                open_stmt = grandparent_holder.transformed.statement
                name = open_stmt.this.name
                value = query.statement
                query.object_mapping.set_variable(name=name, value=value)

    elif isinstance(query, FetchQuery):
        # FETCH <source> INTO <target>;
        # Look up the value for the key and write it to the new key.
        # TODO: should we just substitute the query as the variable?
        var_key: exp.Identifier = query.statement.this
        var_val = query.object_mapping.get_variable(name=var_key.name)
        # TODO: support multiple targets
        new_key: exp.Column = query.statement.args["expressions"][0]
        query.object_mapping.set_variable(name=new_key.name, value=var_val)


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
    return new_query


def _transform_statement(statement: E, query: Q) -> exp.Expr:
    """
    Perform a series of transformations against an SQL statement.
    Dispatches to the appropriate transformer class based on the query type.
    """
    logger.debug("---- Transformer ---")
    logger.debug(f"Query: {statement.sql(dialect=query.dialect)}")

    transformer = BaseQueryTransformer.from_query(query.__class__)
    transformer.prepare(statement, query)

    logger.debug(f"Transforming: {type(query).__name__} - {statement.__class__} using {type(transformer).__name__}")

    stmt = transformer.preprocess(statement)
    logger.debug(f"After pre-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.transform(stmt)
    logger.debug(f"After process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.postprocess(stmt)
    logger.debug(f"After post-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    logger.debug("---- Transformer End ---")
    return stmt
