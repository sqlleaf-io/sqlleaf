import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from sqlleaf import exception, mappings, util
from sqlleaf.objects.query_types import StageQuery, ProcedureQuery, TriggerQuery, UserDefinedFunctionQuery, CTASQuery, ViewQuery, SequenceQuery, TableQuery, SelectQuery, PutQuery, CopyQuery, UpdateQuery, InsertQuery, MergeQuery, Query
from sqlleaf.processors.transformer import clean_stored_procedure_text

logger = logging.getLogger("sqleaf")

DMLQueryType = t.Union[exp.Insert, exp.Update, exp.Merge, exp.Select]

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


def _collect_writable_cte_queries(parent_query: Query, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Transform any writable CTE statements into a form.

    If this query is of the form:
        WITH cte AS (
            INSERT ... RETURNING ...
        )
        INSERT INTO ...

    then the outer and inner queries form a parent-child relationship.
    The inner query is left as-is and copied, while the outer query transforms its
    inner query's SELECT columns with the RETURNING columns. This is so that
    the lineage functions collect the right columns during expression traversal.
    The two queries are processed independently later.
    """
    for i, cte in enumerate(getattr(parent_query.statement, 'ctes', [])):
        cte_expr = cte.this

        if isinstance(cte_expr, exp.Merge):
            query = MergeQuery(expr=cte_expr, dialect=dialect, object_mapping=object_mapping, statement_index=i)
        elif isinstance(cte_expr, exp.Insert):
            query = InsertQuery(expr=cte_expr, dialect=dialect, object_mapping=object_mapping, statement_index=i)
        elif isinstance(cte_expr, exp.Update):
            query = UpdateQuery(expr=cte_expr, dialect=dialect, statement_index=i)
        else:
            logger.warning(f"Skipping unsupported query type in CTE: {type(cte_expr)}")
            continue

        # Detach the query in the AST so that certain transformations work later
        query.statement.pop()
        parent_query.add_child_query(query)


def _collect_merge_children(parent_query: MergeQuery, object_mapping: mappings.ObjectMapping):
    """
    Transform any nested statements (INSERT or UPDATE) into fully qualified queries.

    This is to allow the statements to be processed independently of the parent MERGE query.

    For example, the merge query:

        MERGE INTO fruit.processed AS t
        USING fruit.raw AS s
        ON t.kind = s.kind
        WHEN MATCHED THEN
            UPDATE SET name = s.name
        WHEN NOT MATCHED THEN
            INSERT (label) VALUES (s.kind);

    has 2 nested queries that get transformed into:

        UPDATE fruit.processed AS t
        SET name = s.name
        FROM fruit.raw AS t
        WHERE t.kind = s.kind

        INSERT INTO fruit.processed t
        SELECT s.kind as label
        FROM fruit.raw s;
    """
    merge = parent_query
    expr = parent_query.statement
    whens = [when.args["then"] for when in expr.args["whens"].expressions]

    for i, when in enumerate(whens):
        if isinstance(when, exp.Update):
            update_query = UpdateQuery(expr=when, dialect=parent_query.dialect, statement_index=i)
            update_query.child_table = merge.child_table
            parent_query.add_child_query(update_query)

        elif isinstance(when, exp.Insert):
            insert_query = InsertQuery(expr=when, dialect=parent_query.dialect, object_mapping=object_mapping, statement_index=i)
            insert_query.child_table = merge.child_table
            merge.add_child_query(insert_query)


def _set_column_defs(query: TableQuery, object_mapping: mappings.ObjectMapping):
    """
    Collect all the column definitions for this table.
    """
    statement = query.statement
    columns = list(statement.find_all(exp.ColumnDef))

    # Set the column's 'default' type to the column's own type (it is sometimes missing)
    for col_def in columns:
        if default := col_def.find(exp.DefaultColumnConstraint):
            default.this.type = col_def.kind

    # Process the table's properties: INHERITS, LIKE, etc
    if inherited_props := list(statement.find_all(exp.InheritsProperty)):
        inherited_columns = _find_inherited_columns(inherited_props, object_mapping)
        columns += inherited_columns

    if like_property := statement.find(exp.LikeProperty):
        like_columns = _find_like_columns(like_property, object_mapping, query.child_table)
        columns += like_columns

    query.column_defs = columns


def _find_inherited_columns(inherits_properties: t.List[exp.InheritsProperty], object_mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
    """
    Search for tables referenced as 'CREATE TABLE b INHERITS (a)'
    """
    columns = []

    for inh_prop in inherits_properties:
        inh_table = inh_prop.find(exp.Table)
        inh_table_query = object_mapping.find_query(kind='table', table=inh_table)
        columns.extend(inh_table_query.column_defs)

    return columns

def _find_like_columns(like_property: exp.LikeProperty, object_mapping: mappings.ObjectMapping, child_table: exp.Table) -> t.List[exp.ColumnDef]:
    """
    Search for tables referenced as 'CREATE TABLE b (LIKE a)'.
    Postgres allows only 1 table to be referenced in LIKE.
    """
    columns = []
    property_names = []

    for like_prop in like_property.expressions:
        # sqlglot concats properties with '='
        property_names.append(str(like_prop).replace('=', ' '))

    properties = _get_properties_to_include(property_names)

    # Look up the like-table's columns and determine which properties to transfer
    parent_table_query = object_mapping.find_query(kind='table', table=like_property.this)
    parent_columns = parent_table_query.column_defs

    for parent_col_def in parent_columns:
        new_col = parent_col_def.copy()
        for prop_name, prop_attrs in properties.items():
            prop_expr = new_col.find(prop_attrs["expr"])

            if properties[prop_name]["include"]:
                # Set the expression's parent to be the new table (it's missing)
                if prop_expr:
                    for inner_col in prop_expr.find_all(exp.Column):
                        # A GENERATED column expression might refer to other columns
                        try:
                            referenced_parent_col_def = [c for c in parent_columns if c.name == inner_col.name][0]
                        except IndexError:
                            message = f"Column '{inner_col.name}' does not exist in table '{child_table}'."
                            raise exception.SqlLeafException(message=message)

                        inner_col.set('catalog', exp.to_identifier(child_table.catalog))
                        inner_col.set('db', exp.to_identifier(child_table.db))
                        inner_col.set('table', exp.to_identifier(child_table.this))
                        inner_col.type = referenced_parent_col_def.kind
            else:
                # Discard the column's expression
                if prop_expr:
                    prop_expr.parent.pop()

        columns.append(new_col)

    return columns


def _get_properties_to_include(options: t.List[str]) -> t.Dict:
    """
    Determine which column properties to keep within a LIKE according to the rules below.

    From the Postgres docs:
        Specifying INCLUDING copies the property, specifying EXCLUDING omits the property.
        EXCLUDING is the default. If multiple specifications are made for the same kind
        of object, the last one is used. It could be useful to write individual EXCLUDING
        clauses after INCLUDING ALL to select all but some specific options.
    """
    # All supported properties
    properties = {
          "DEFAULTS": {
            "include": False,
            "expr": exp.DefaultColumnConstraint
        },
        "GENERATED": {
            "include": False,
            "expr": exp.ComputedColumnConstraint
        },
        "IDENTITY": {
            "include": False,
            "expr": exp.GeneratedAsIdentityColumnConstraint
        }
    }

    for opt in options:
        opt = opt.strip().upper()

        if opt == "INCLUDING ALL":
            for prop in properties:
                properties[prop]["include"] = True
            continue

        if opt == "EXCLUDING ALL":
            for prop in properties:
                properties[prop]["include"] = False
            continue

        parts = opt.split()
        action, prop = parts

        if prop not in properties:
            continue  # Ignore unknown properties

        if action == "INCLUDING":
            properties[prop]["include"] = True
        elif action == "EXCLUDING":
            properties[prop]["include"] = False

    return properties


def _process_unnamed(statement: exp.Expression, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process an unnamed statement - one not inside a 'CREATE <name>' statement.
    """
    query = None

    if isinstance(statement, exp.Insert):
        query = InsertQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Update):
        query = UpdateQuery(expr=statement, dialect=dialect, statement_index=statement_index)
    elif isinstance(statement, exp.Copy):
        return CopyQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Put):
        return PutQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
    elif isinstance(statement, exp.Select):
        if statement.find((exp.Insert, exp.Update, exp.Merge)):
            query = SelectQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
        else:
            logger.warning("Skipping statement: A SELECT query must have a data-modifying statement, such as an INSERT, to contain lineage.")

    if isinstance(statement, exp.Merge):
        query = MergeQuery(expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
        _collect_merge_children(query, object_mapping)

    _collect_writable_cte_queries(query, dialect, object_mapping)

    return query


def _process_tables(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    """
    Process a 'CREATE TABLE' statement.
    """
    if statement.kind == "TABLE":
        # CREATE TABLE ...
        query = TableQuery(statement=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index)
        _set_column_defs(query, object_mapping)
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
    # Add types from the mapping if available. Views often have unknown column types.
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
    transformed_text = clean_stored_procedure_text(query.text_original)
    query.text_transformed = transformed_text

    # The original text is lost, so we are forced to use the transformed text in its place for now
    queries = collect_queries(text=transformed_text, dialect=dialect, object_mapping=object_mapping)
    query.add_child_queries(child_queries=queries)
    return query

def _process_stage(statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int) -> Query:
    query = StageQuery(statement, dialect, statement_index)
    object_mapping.add_query(kind='stage', query=query, dialect=dialect)
    return query
