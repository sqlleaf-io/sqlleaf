import logging

from sqlglot import exp

from sqlleaf import util
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import (
    AssignmentQuery,
    CTASQuery,
    ExecuteDynamicQuery,
    FetchQuery,
    ForInQuery,
    InsertQuery,
    OpenQuery,
    Q,
    QueryHolder,
    SelectQuery,
    ViewQuery,
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
    # TODO: separate this into its own 'variable' object/class (along with transformer.replace_variables_in_expression())
    if isinstance(query, AssignmentQuery):
        # `my_var := 42`
        name = query.get_key()
        value = query.get_value()
        if query.is_declaration:
            query.object_mapping.declare_variable(name=name, value=value)
        else:
            query.object_mapping.set_variable(name=name, value=value)

    elif isinstance(query, SelectQuery):
        original_stmt = query.holder.original.statement
        original_parent = original_stmt.parent
        parent_holder = query.holder.parent_holder

        if isinstance(original_parent, pgexp.PGForIn) and original_parent.args["query"] == original_stmt:
            # `FOR .. IN SELECT ..`
            name = original_parent.this.name
            value = query.statement
            query.object_mapping.set_variable(name=name, value=value)

        elif isinstance(original_parent, pgexp.PGOpen) and original_parent.args.get("expression") == original_stmt:
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

    elif isinstance(query, FetchQuery):
        # FETCH <source> INTO <target>;
        # Look up the value for the key and write it to the new key.
        # TODO: should we just substitute the query as the variable?
        var_key: exp.Identifier = query.statement.this
        var_val = query.object_mapping.get_variable(name=var_key.name)
        targets = query.statement.args["expressions"]

        if len(targets) == 1:
            query.object_mapping.set_variable(name=targets[0].name, value=var_val)
        else:
            source_columns = var_val.selects if isinstance(var_val, exp.Query) else []
            for i, target in enumerate(targets):
                if i < len(source_columns):
                    value = exp.Dot(
                        this=var_val.subquery(),
                        expression=exp.to_identifier(source_columns[i].alias_or_name),
                    )
                else:
                    value = var_val
                query.object_mapping.set_variable(name=target.name, value=value)

    elif isinstance(query, OpenQuery):
        query.object_mapping.set_variable(name=query.target().name, value=query.source())


def _transform_query_instance(query: Q) -> Q:
    """
    Helper to transform a Query instance.
    """
    initial_statement = util.copy_expression(query.statement)

    # TODO: figure out a proper way to select the statement to transform
    statement_to_transform = initial_statement

    transformed_statement = _transform_statement(statement=statement_to_transform, query=query)

    if isinstance(initial_statement, pgexp.PGOpen):
        transformed_statement = initial_statement

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
        )
    else:
        # For statements not converted to INSERT, keep the same Query subclass but with the new statement.
        kwargs = {
            "expr": transformed_statement,
            "dialect": original_query.dialect,
            "object_mapping": original_query.object_mapping,
            "statement_index": original_query.statement_index,
        }
        # TODO: look at the kwargs of the Query class and copy their attrs
        cls = type(original_query)
        if cls == CTASQuery:
            kwargs |= {"columns": original_query.column_defs, "system_columns": original_query.system_column_defs}
        elif cls == ViewQuery:
            kwargs |= {"columns": original_query.column_defs}

        new_query = cls(**kwargs)

    return new_query


def _transform_statement(statement: E, query: Q) -> exp.Expr:
    """
    Perform a series of transformations against an SQL statement.
    Dispatches to the appropriate transformer class based on the query type.
    """
    logger.debug("---- Transformer ---")
    logger.debug(f"Query: {statement.sql(dialect=query.dialect)}")

    transformer = BaseQueryTransformer.from_query(query)

    logger.debug(f"Transforming: {type(query).__name__} - {statement.__class__} using {type(transformer).__name__}")

    stmt = transformer.preprocess(statement)
    logger.debug(f"After pre-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.transform(stmt)
    logger.debug(f"After process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    stmt = transformer.postprocess(stmt)
    logger.debug(f"After post-process: {type(stmt)} - {stmt.sql(dialect=query.dialect)}")
    logger.debug("---- Transformer End ---")
    return stmt
