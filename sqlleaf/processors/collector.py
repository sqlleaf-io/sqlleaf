import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from sqlleaf import transform, exception, mappings, util
from sqlleaf.objects.query_types import StageQuery, ProcedureQuery, TriggerQuery, UserDefinedFunctionQuery, CTASQuery, ViewQuery, SequenceQuery, TableQuery, SelectQuery, PutQuery, CopyQuery, UpdateQuery, InsertQuery, MergeQuery, Query

logger = logging.getLogger("sqleaf")

"""
Parses text for SQL statements and collects them into Query objects.
"""


def get_query_processors():
    return {
        "table": _process_tables,
        "ctas": _process_views_and_ctas,
        "view": _process_views_and_ctas,
        "sequence": _process_tables,
        "procedure": _process_stored_procedures,
        "function": _process_functions,
        "trigger": _process_triggers,
        "select": _process_unnamed,
        "insert": _process_unnamed,
        "update": _process_unnamed,
        "merge": _process_unnamed,
        "stage": _process_stage,
        "copy": _process_unnamed,
        "put": _process_unnamed,
    }


def collect_queries(text: str, dialect: str, object_mapping: mappings.ObjectMapping) -> t.List[Query]:
    """
    Parse a series of SQL statements provided as text.
    This includes tables, views, procedures, functions, sequences, etc.

    The statements must be provided in the order in which they depend.
    If B depends on A, A must be created before B.
    """
    queries = {}
    unsupported = []
    processors = get_query_processors()
    counts = {kind: 0 for kind in processors.keys()}
    parsed = sqlglot.parse(text, dialect=dialect)

    for index, stmt in enumerate(parsed):
        if isinstance(stmt, exp.Command):
            unsupported.append((index, stmt))
            continue

        # Remove duplicate queries
        _id = util.short_sha256_hash(stmt.sql())
        if _id in queries:
            logger.debug(f"Skipping duplicate query: {stmt.sql()}")
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

        skip_kinds = ["transaction", "commit", "rollback", "endstatement", "alias", "semicolon"]
        if kind in skip_kinds:
            logger.debug(f"Skipping statement kind: {kind}")
            unsupported.append((index, stmt))
            continue

        if kind not in processors:
            raise exception.SqlLeafException(message=f"Unsupported query kind: '{kind}'. Are you missing a processor for this kind?")

        # Convert the statement to uppercase if the dialect supports it
        stmt = normalize_identifiers(stmt, dialect=dialect, store_original_column_identifiers=True)

        query: Query = processors[kind](statement=stmt, dialect=dialect, object_mapping=object_mapping, statement_index=index)
        if query:
            queries[_id] = query
            counts[kind] += 1

    logger.debug("Found statements: %s", dict(counts.items()))
    logger.warning("Unsupported statements: %s", len(unsupported))
    return list(queries.values())


def _process_unnamed(statement: exp.Expression, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process an unnamed statement - one not inside a 'CREATE <name>' statement.
    """
    query = None

    if isinstance(statement, exp.Merge):
        query = MergeQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    if isinstance(statement, exp.Insert):
        query = InsertQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Update):
        query = UpdateQuery(expr=statement, dialect=dialect, statement_index=statement_index)
    elif isinstance(statement, exp.Copy):
        query = CopyQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Put):
        query = PutQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Select):
        if statement.find(exp.Insert, exp.Update, exp.Merge):
            query = SelectQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
        else:
            logger.warning("Skipping statement: A SELECT query must have a data-modifying statement, such as an INSERT, to contain lineage.")
    return query


def _process_tables(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process a 'CREATE TABLE' statement.
    """
    if statement.kind == "TABLE":
        # CREATE TABLE ...
        query = TableQuery(statement=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
        object_mapping.add_query(
            kind='table',
            query=query,
            column_mapping=query.get_column_names_with_types(),
            match_depth=False,
            dialect=dialect,
        )
    elif statement.kind == "SEQUENCE":
        query = SequenceQuery(statement=statement, dialect=dialect, statement_index=statement_index)
        object_mapping.add_query(kind='sequence', query=query, dialect=dialect)
    return query


def _process_views_and_ctas(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Convert a series of `CREATE VIEW/TABLE AS ...` SQL DDL statements into sqlglot's MappingSchema
    to extract the table and column details.
    """
    # Infer schemas, qualify columns, etc
    stmt = qualify(
        statement,
        schema=object_mapping,
        infer_schema=True,
        dialect=dialect,
        isolate_tables=False,
        validate_qualify_columns=False,
        quote_identifiers=False,
    )
    # Add types from the mapping if available
    stmt = annotate_types(stmt, dialect=dialect, schema=object_mapping)

    col_defs = [exp.ColumnDef(this=exp.to_identifier(s.alias), kind=s.type) for s in stmt.selects]

    if stmt.kind == "VIEW":
        # CREATE VIEW ...
        query = ViewQuery(statement=stmt, dialect=dialect, columns=col_defs, statement_index=statement_index)

    elif stmt.kind == "TABLE":
        # CREATE TABLE AS SELECT ...
        query = CTASQuery(statement=stmt, dialect=dialect, columns=col_defs, statement_index=statement_index)

    object_mapping.add_query(
        kind='table',
        query=query,
        column_mapping=query.get_column_names_with_types(),
        match_depth=False,
    )
    return query


def _process_functions(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
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

    props = statement.args["properties"].expressions
    for prop in props:
        if isinstance(prop, exp.ReturnsProperty):
            if prop.args["null"]:
                returns_null = True
            else:
                return_type = prop.this
        elif isinstance(prop, exp.LanguageProperty):
            language = prop.name

    query = UserDefinedFunctionQuery(
        statement=statement,
        schema=udf_table.db,
        function=udf_table.name,
        dialect=dialect,
        args=columns,
        return_type=return_type,
        return_expr=return_expr,
        returns_null=returns_null,
        language=language,
        statement_index=statement_index
    )
    object_mapping.add_query(kind='udf', query=query, dialect=dialect)

    if isinstance(statement.expression, exp.Heredoc):
        # Extract the queries between the $$ .. $$
        queries = collect_queries(text=statement.expression.this, dialect=dialect, object_mapping=object_mapping)
        query.add_child_queries(child_queries=queries)

    return query


def _process_triggers(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process a "CREATE TRIGGER" statement.
    """
    query = TriggerQuery(statement, dialect)
    object_mapping.add_query(kind='trigger', query=query, dialect=dialect)
    return query


def _process_stored_procedures(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process a "CREATE PROCEDURE" statement.
    """
    query = ProcedureQuery(statement=statement, dialect=dialect, statement_index=statement_index)
    object_mapping.add_query(kind='procedure', query=query, dialect=dialect)
    # TODO: find a way to get each SP's text from a query that has multiple SPs defined in it.
    #  sqlglot will parse the 2 SPs, but does not provide the original, raw text. This is imperfect
    #  as we would like to keep the original text for various reasons.
    transformed_text = transform.clean_stored_procedure_text(query.text_original)
    query.text_transformed = transformed_text

    # The original text is lost, so we are forced to use the transformed text in its place for now
    queries = collect_queries(text=transformed_text, dialect=dialect, object_mapping=object_mapping)
    query.add_child_queries(child_queries=queries)
    return query

def _process_stage(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    query = StageQuery(statement, dialect, statement_index)
    object_mapping.add_query(kind='stage', query=query, dialect=dialect)
    return query
