import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.optimizer import qualify
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from sqlleaf import structs, transform, exception, mappings

logger = logging.getLogger("sqleaf")


# TODO: determine dependency order based on object relations
def get_processors():
    return {
        "table": _process_tables,
        "ctas": _process_views_and_ctas,
        "view": _process_views_and_ctas,
        "sequence": _process_tables,
        "procedure": _process_stored_procedures,
        "function": _process_functions,
        "trigger": _process_triggers,
        "insert": _process_unnamed,
        "update": _process_unnamed,
        "merge": _process_unnamed,
        "stage": _process_stage,
        "copy": _process_unnamed,
        "put": _process_unnamed,
    }


def produce_query_objects(statement: exp.Expression, dialect: str, statement_index: int) -> structs.Query:
    """
    This follows the same pattern as `walk_tree_and_build_graph()`

    Args:
        statement_index: the order of the statement in a list of statements.
    """
    query = None

    if isinstance(statement, exp.Merge):
        query = structs.MergeQuery(expr=statement, dialect=dialect, index=statement_index)

        # Link any child queries
        for child_expr in query.get_child_expressions():
            statement_index += 1
            child_query = produce_query_objects(statement=child_expr, dialect=dialect, statement_index=statement_index)
            query.add_child_query(child_query)

    elif isinstance(statement, exp.Insert):
        query = structs.InsertQuery(expr=statement, dialect=dialect, index=statement_index)
    elif isinstance(statement, exp.Update):
        query = structs.UpdateQuery(expr=statement, dialect=dialect, index=statement_index)

    return query


def get_queries_from_sql(text: str, dialect: str, include_selects=False) -> t.List[structs.Query]:
    """
    Extract all the SQL queries from some text.
    """
    queries = []

    try:
        statements = sqlglot.parse(text, dialect=dialect)
        statements = [statement for statement in statements if statement]
    except Exception as e:
        raise exception.SqlGlotException(message=e, table="")

    supported_statements = (
        exp.Insert,
        exp.Update,
        exp.Merge,
    )
    if include_selects:
        supported_statements += (exp.Select,)

    # Process each of the statements
    for statement_index, statement in enumerate(statements):
        logger.info(f"Processing parsed statement {statement_index + 1}/{len(statements)} - {str(type(statement))}")

        if isinstance(statement, exp.Command) and statement.this == "CALL":
            # TODO: add hooks to allow users to include custom logic
            logging.info("Skipping CALL statement.")
            continue

        elif not isinstance(statement, supported_statements):
            logging.info(f"Skipping unsupported '{type(statement)}' statement.")
            continue

        query = produce_query_objects(statement, dialect, statement_index)
        queries.append(query)

    return queries


def collect_queries(text: str, dialect: str, object_mapping: mappings.ObjectMapping) -> (t.List[structs.Query], t.List[exp.Expression]):
    """
    Parse a series of SQL statements provided as text.
    This includes tables, views, procedures, functions, sequences, etc.

    The statements must be provided in the order in which they depend.
    If B depends on A, A must be created before B.
    """
    queries = []
    unrecognised = []
    processors = get_processors()
    counts = {kind: 0 for kind in processors.keys()}
    parsed = sqlglot.parse(text, dialect=dialect)

    for stmt in parsed:
        if isinstance(stmt, exp.Command):
            unrecognised.append(stmt)
            continue

        if stmt.key == "create":
            if stmt.kind == "TABLE":
                if isinstance(stmt.expression, exp.Select):
                    kind = "ctas"
                else:
                    kind = "table"
            else:
                kind = stmt.kind.lower()
        elif stmt.key == "select" and "into" in stmt.args:
            # TODO: this is dialect-dependent! mysql converts, but postgres does not
            # sqlglot rewrites 'SELECT INTO' to 'CREATE TABLE AS' during parse()
            # but it's not shown until we produce it with sql(), so we re-parse it
            stmt = sqlglot.parse_one(stmt.sql(dialect=""), dialect=dialect)
            kind = "ctas"
        else:
            kind = stmt.key.lower()

        # Convert the statement to uppercase if the dialect supports it
        stmt = normalize_identifiers(stmt, dialect=dialect, store_original_column_identifiers=True)

        if kind not in processors:
            raise exception.SqlLeafException(message=f"Unsupported query kind: '{kind}'")

        query = processors[kind](statement=stmt, dialect=dialect, object_mapping=object_mapping)
        queries.append(query)
        counts[kind] += 1

    logger.debug("Found statements: %s", dict(counts.items()))
    logger.warn("Unrecognised statements: %s", len(unrecognised))
    return queries


def _process_unnamed(statement: t.Union[exp.Insert, exp.Update], dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Process a MERGE, INSERT or UPDATE statement.
    """
    if isinstance(statement, exp.Merge):
        query = structs.MergeQuery(expr=statement, dialect=dialect, index=-1)
    if isinstance(statement, exp.Insert):
        query = structs.InsertQuery(expr=statement, dialect=dialect, index=-1)
    elif isinstance(statement, exp.Update):
        query = structs.UpdateQuery(expr=statement, dialect=dialect, index=-1)
    elif isinstance(statement, exp.Copy):
        query = structs.CopyQuery(expr=statement, dialect=dialect, mapping=object_mapping, index=-1)
    elif isinstance(statement, exp.Put):
        query = structs.PutQuery(expr=statement, dialect=dialect, mapping=object_mapping, index=-1)
    return query


def _process_tables(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Process a 'CREATE TABLE' statement.
    """
    if statement.kind == "TABLE":
        # CREATE TABLE ...
        query = structs.TableQuery(statement=statement, dialect=dialect, mapping=object_mapping)
        object_mapping.add_query(
            kind='table',
            query=query,
            column_mapping=query.get_column_names_with_types(),
            match_depth=False,
            dialect=dialect,
        )
    elif statement.kind == "SEQUENCE":
        query = structs.SequenceQuery(statement=statement, dialect=dialect)
        object_mapping.add_query(kind='sequence', query=query, dialect=dialect)
    return query


def _process_views_and_ctas(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Convert a series of `CREATE VIEW/TABLE AS ...` SQL DDL statements into sqlglot's MappingSchema
    to extract the table and column details.

    Parameters:
        statements:
    """
    # Infer schemas, qualify columns, etc
    stmt = sqlglot.optimizer.qualify.qualify(
        statement,
        schema=object_mapping,
        infer_schema=True,
        dialect=dialect,
        isolate_tables=False,
        validate_qualify_columns=False,
        quote_identifiers=False,
    )
    # Add types from the mapping if available
    stmt = sqlglot.optimizer.annotate_types.annotate_types(stmt, dialect=dialect, schema=object_mapping)

    # We may not know the column types until we parse the Creates's SELECT query / connect it to the lineage
    named_columns = {s.alias_or_name: {"default": None, "kind": s.type or "UNKNOWN"} for s in stmt.selects}

    if stmt.kind == "VIEW":
        # CREATE VIEW ...
        query = structs.ViewQuery(statement=stmt, dialect=dialect, columns=named_columns)

    elif stmt.kind == "TABLE":
        # CREATE TABLE AS SELECT ...
        query = structs.CTASQuery(statement=stmt, dialect=dialect, columns=named_columns)

    object_mapping.add_query(
        kind='table',
        query=query,
        column_mapping=query.get_column_names_with_types(),
        match_depth=False,
    )
    return query


def _process_functions(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Process a "CREATE FUNCTION" statement.
    """
    # TODO: Decide if we can process it or not (i.e. lang = SQL)

    udf_expr = statement.this
    udf_table = statement.this.this
    columns = [col for col in udf_expr.expressions if isinstance(col, exp.ColumnDef)]

    language = ""
    returns_null = False
    return_type = None
    return_expr = statement.expression.this  # ADD(a, b)

    if isinstance(statement.expression, exp.Heredoc):
        # Extract the queries between the $$ .. $$
        queries = get_queries_from_sql(
            text=statement.expression.this,
            dialect=dialect,
            include_selects=True,
        )

    props = statement.args["properties"].expressions
    for prop in props:
        if isinstance(prop, exp.ReturnsProperty):
            if prop.args["null"]:
                returns_null = True
            else:
                return_type = prop.this
        elif isinstance(prop, exp.LanguageProperty):
            language = prop.name

    query = structs.UserDefinedFunctionQuery(
        statement=statement,
        schema=udf_table.db,
        function=udf_table.name,
        dialect=dialect,
        args=columns,
        return_type=return_type,
        return_expr=return_expr,
        returns_null=returns_null,
        language=language,
    )
    object_mapping.add_query(kind='udf', query=query, dialect=dialect)

    # TODO: swap this with produce_query_objects() like MERGE
    queries = get_queries_from_sql(text=return_expr.sql(), dialect=dialect)
    query.add_child_queries(child_queries=queries)
    return query


def _process_triggers(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Process a "CREATE TRIGGER" statement.
    """
    query = structs.TriggerQuery(statement, dialect)
    object_mapping.add_query(kind='trigger', query=query, dialect=dialect)
    return query


def _process_stored_procedures(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Process a "CREATE PROCEDURE" statement.
    """
    query = structs.ProcedureQuery(statement=statement, dialect=dialect)
    object_mapping.add_query(kind='procedure', query=query, dialect=dialect)
    # TODO: find a way to get each SP's text from a query that has multiple SPs defined in it.
    #  sqlglot will parse the 2 SPs, but does not provide the original, raw text. This is imperfect
    #  as we would like to keep the original text for various reasons.
    transformed_text = transform.clean_stored_procedure_text(query.text_original)
    query.text_transformed = transformed_text

    # The original text is lost, so we are forced to use the transformed text in its place for now
    queries = get_queries_from_sql(text=transformed_text, dialect=dialect)
    query.add_child_queries(child_queries=queries)
    return query

def _process_stage(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping):
    query = structs.StageQuery(statement, dialect)
    object_mapping.add_query(kind='stage', query=query, dialect=dialect)
    return query
