import logging
import typing as t
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.dialects import postgres
from sqlglot.expressions import ColumnDef
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
from sqlglot.optimizer.qualify import qualify

from sqlleaf import exception, mappings, util
from sqlleaf.models.query import (
    CopyQuery,
    CTASQuery,
    DatabaseQuery,
    DeleteQuery,
    InsertQuery,
    MergeQuery,
    ProcedureQuery,
    PutQuery,
    Q,
    QueryHolder,
    SchemaQuery,
    SelectQuery,
    SequenceQuery,
    StageQuery,
    TableQuery,
    TriggerQuery,
    TypeQuery,
    UnloadQuery,
    UpdateQuery,
    UserDefinedFunctionQuery,
    ViewQuery,
)

logger = logging.getLogger("sqlleaf")

# sqlglot is missing pseudocolumns for Postgres
PSEUDOCOLUMNS = ["ctid", "xmin", "xmax", "cmin", "cmax", "tableoid", "oid"]
postgres.Postgres.PSEUDOCOLUMNS = {c.upper() for c in PSEUDOCOLUMNS}
postgres.Postgres.EXCLUDES_PSEUDOCOLUMNS_FROM_STAR = True


"""
Parses text for SQL statements and collects them into Query models.
"""


def get_query_processors():
    return {
        "table": _process_tables,
        "ctas": _process_views_and_ctas,
        "view": _process_views_and_ctas,
        "sequence": _process_tables,
        "procedure": _process_stored_procedures,
        "function": _process_functions,
        "database": _process_database,
        "trigger": _process_triggers,
        "select": _process_unnamed,
        "insert": _process_unnamed,
        "update": _process_unnamed,
        "merge": _process_unnamed,
        "delete": _process_unnamed,
        "schema": _process_schema,
        "unload": _process_unload,
        "stage": _process_stage,
        "copy": _process_unnamed,
        "put": _process_unnamed,
        "type": _process_type,
    }


@dataclass(frozen=True)
class CollectQueryResult:
    queries: t.List = field(default_factory=list)  # Successfully collected queries
    unknown: t.Dict = field(default_factory=dict)  # Unsupported by sqlleaf (no handler)
    unsupported: t.List = field(default_factory=list)  # Unsupported by sqlglot (no grammar)


def collect_queries(text: str, dialect: str, object_mapping: mappings.ObjectMapping) -> CollectQueryResult:
    """
    Parse a series of SQL statements provided as text.
    This includes tables, views, procedures, functions, sequences, etc.

    Each query may contain multiple child queries. For example, a stored procedure often
    has multiple individual queries. Each of these individual queries may also have
    subqueries. For example, a MERGE query often has INSERTs or UPDATEs in its WHEN clauses.

    The statements must be provided in the order in which they depend on each other.
    If B depends on A, A must be created before B.
    """
    queries = {}
    unknown = {}
    unsupported = []
    processors = get_query_processors()
    counts = {kind: 0 for kind in processors.keys()}
    parsed = sqlglot.parse(text, dialect=dialect)

    for index, stmt in enumerate(parsed):
        if not stmt:
            continue

        # Remove comments at initialization
        for expr in stmt.walk():
            expr.pop_comments()

        kind = ""
        if isinstance(stmt, exp.Command):
            if dialect == "redshift" and stmt.name == "UNLOAD":
                kind = "unload"
            else:
                logger.warning(f"Unsupported statement: {stmt.sql(dialect=dialect)}")
                unsupported.append((index, stmt))
                continue

        # Remove duplicate queries
        sql_text = stmt.sql(dialect=dialect)
        _id = util.short_sha256_hash(sql_text)
        if _id in queries:
            logger.debug(f"Skipping duplicate query: {sql_text}")
            continue

        if not kind:
            stmt, kind = _determine_query_kind(stmt, kind)

        if kind not in processors:
            unknown[kind] = unknown[kind] + 1 if kind in unknown else 1
            continue

        # Convert the statement to uppercase if the dialect supports it
        stmt = normalize_identifiers(stmt, dialect=dialect, store_original_column_identifiers=True)

        query: t.Optional[Q] = processors[kind](
            statement=stmt, dialect=dialect, object_mapping=object_mapping, statement_index=index
        )
        if query:
            holder = QueryHolder(original=query)
            _collect_query_children(query, holder, dialect, object_mapping)
            queries[_id] = holder
            counts[kind] += 1

    found = {k: v for k, v in counts.items() if v > 0}
    logger.debug("Found statements: %s", dict(found.items()))
    if unknown:
        logger.warning("Unknown statements: %s", dict(unknown.items()))
    if unsupported:
        logger.warning("Unsupported statements: %s", len(unsupported))

    return CollectQueryResult(queries=list(queries.values()), unknown=unknown, unsupported=unsupported)


def _determine_query_kind(statement: exp.Expr, dialect: str) -> t.Tuple[exp.Expr, str]:
    """
    Determine a query's "kind" from the expression, which maps to how it will be processed.
    """
    if statement.key == "create" and isinstance(statement, exp.Create):
        if statement.kind == "TABLE":
            if isinstance(statement.expression, (exp.Select, exp.Values)):
                kind = "ctas"
            else:
                kind = "table"
        else:
            kind = (statement.kind or "").lower()
    elif statement.key == "select" and "into" in statement.args:
        # sqlglot rewrites 'SELECT INTO' to 'CREATE TABLE AS' during parse()
        # but it's not shown until we produce it with sql(), so we re-parse it
        if dialect not in ["redshift", "postgres"]:
            statement = sqlglot.parse_one(statement.sql(dialect=dialect), dialect=dialect)
            kind = "ctas"
        else:
            message = f"Expression 'SELECT INTO' has not been implemented yet for dialect: {dialect}"
            raise exception.SqlLeafException(message=message)
    else:
        kind = statement.key.lower()

    return statement, kind


def _collect_writable_cte_queries(
    parent_query: Q, parent_holder: QueryHolder, dialect: str, object_mapping: mappings.ObjectMapping
):
    """
    Transform any writable CTE statements into a form.

    If this query is of the form:
        WITH cte AS (
            INSERT ... RETURNING ...
        )
        INSERT INTO ...

    then the outer and inner queries form a parent-child relationship.
    The inner query is left as-is and copied, while the outer query transformers its
    inner query's SELECT columns with the RETURNING columns. This is so that
    the lineage functions collect the right columns during expression traversal.
    The two queries are processed independently later.
    """
    for i, cte in enumerate(parent_query.get_ctes()):
        cte_expr = cte.this

        if isinstance(cte_expr, exp.Select):
            continue

        query = _process_unnamed(cte_expr, dialect, object_mapping, i)
        if not query:
            logger.warning(f"Skipping unsupported query type in CTE: {type(cte_expr)}")
            continue

        # Detach the query in the AST so that certain transformations work later
        child_holder = QueryHolder(original=query)
        parent_holder.add_child_holder(child_holder)
        _collect_query_children(query, child_holder, dialect, object_mapping)


def _collect_query_children(query: Q, parent_holder: QueryHolder, dialect: str, object_mapping: mappings.ObjectMapping):
    """
    Collect any nested child queries for a given query and attach them to the holder.
    """
    if isinstance(query, InsertQuery):
        _collect_insert_children(query, parent_holder, object_mapping)
    if isinstance(query, MergeQuery):
        _collect_merge_children(query, parent_holder, object_mapping)
    if not isinstance(query, (CopyQuery, PutQuery)):
        _collect_writable_cte_queries(query, parent_holder, dialect, object_mapping)


def _collect_insert_children(query: InsertQuery, parent_holder: QueryHolder, object_mapping: mappings.ObjectMapping):
    """
    Collect any additional queries inside an INSERT. For Postgres, this is 'INSERT .. ON CONFLICT DO UPDATE'.
    """
    on_conflict = query.statement.args["conflict"]

    if not isinstance(on_conflict, exp.OnConflict) or on_conflict.args["action"].name == "DO NOTHING":
        return

    update_query = UpdateQuery(
        expr=on_conflict,
        dialect=query.dialect,
        object_mapping=object_mapping,
        statement_index=0,
        table=query.get_target_as_table(),
    )
    child_holder = QueryHolder(original=update_query)
    parent_holder.add_child_holder(child_holder)


def _collect_merge_children(
    parent_query: MergeQuery, parent_holder: QueryHolder, object_mapping: mappings.ObjectMapping
):
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
    parent_expr = parent_query.statement
    whens = [when.args["then"] for when in parent_expr.args["whens"].expressions]

    for i, when in enumerate(whens):
        # Ensure the full expression tree is kept
        when_expr = util.copy_expression(when)

        if isinstance(when_expr, exp.Update):
            update_query = UpdateQuery(
                expr=when_expr,
                dialect=parent_query.dialect,
                object_mapping=object_mapping,
                statement_index=i,
                table=merge.get_target_as_table(),
            )
            child_holder = QueryHolder(original=update_query)
            parent_holder.add_child_holder(child_holder)

        elif isinstance(when_expr, exp.Insert):
            insert_query = InsertQuery(
                expr=when_expr,
                dialect=parent_query.dialect,
                object_mapping=object_mapping,
                statement_index=i,
                table=merge.get_target_as_table(),
            )
            insert_query.target_info = merge.target_info
            child_holder = QueryHolder(original=insert_query)
            parent_holder.add_child_holder(child_holder)


def _set_column_defs(query: TableQuery):
    """
    Collect all the column definitions for this table.
    """
    statement = query.statement
    all_columns = []

    for expression in statement.this.expressions:
        if isinstance(expression, exp.ColumnDef):
            all_columns.append(expression)
        elif isinstance(expression, exp.LikeProperty):
            like_columns = _collect_like_columns(expression, query.object_mapping, query.get_target_as_table())
            all_columns.extend(like_columns)
        elif isinstance(expression, exp.Identifier):
            # CREATE TABLE (a INT, b);
            raise exception.SqlLeafException(message=f"Column '{expression.name}' must define a data type.")
        else:
            raise exception.SqlLeafException(message=f"Unsupported column expression: {type(expression)}")

    if inherited_props := list(statement.find_all(exp.InheritsProperty)):
        inherited_columns = _collect_inherited_columns(inherited_props, query)
        all_columns = inherited_columns + all_columns

    # Set the column's 'default' type to the column's own type (it is sometimes missing)
    for col_def in all_columns:
        if default := col_def.find(exp.DefaultColumnConstraint):
            default.this.type = col_def.kind

    query.column_defs = all_columns
    query.system_column_defs = _system_columns(dialect=query.dialect)


def _system_columns(dialect: str) -> t.List[exp.ColumnDef]:
    """
    Create a set of ColumnDefs representing system columns for a given dialect.
    """
    col_defs = []
    if dialect == "postgres":
        data_type = exp.DataType.build("OID", dialect="postgres")
        col_defs = [exp.ColumnDef(this=exp.to_identifier(name), kind=data_type) for name in PSEUDOCOLUMNS]

    return col_defs


def _collect_inherited_columns(
    inherits_properties: t.List[exp.InheritsProperty], query: TableQuery
) -> t.List[exp.ColumnDef]:
    """
    Search for tables referenced as 'CREATE TABLE b INHERITS (a)' and collect all their columns.
    A table can have multiple tables in an INHERITS clause.
    """
    column_defs = []

    for inh_prop in inherits_properties:
        for inh_table in inh_prop.expressions:
            parent_table_query = t.cast(TableQuery, query.object_mapping.lookup_table_query(table=inh_table))
            parent_table_query.inherited_by.append(query)
            query.inherits.append(parent_table_query)

            # Re-assign the columns to a copy of the correct table
            expr = query.get_target_expression()
            if expr.parent:
                schema = util.copy_expression(expr.parent)
                for parent_col_def in parent_table_query.column_defs:
                    col_def = parent_col_def.copy()
                    schema.append("expressions", col_def)
                    column_defs.append(col_def)

    return column_defs


def _collect_like_columns(
    like_property: exp.LikeProperty, object_mapping: mappings.ObjectMapping, child_object: exp.Table
) -> t.List[exp.ColumnDef]:
    """
    Search for tables referenced as 'CREATE TABLE b (LIKE a)'.
    A table can have multiple LIKE clauses.
    """
    columns = []
    property_names = []

    for like_prop in like_property.expressions:
        # sqlglot concats properties with '='
        property_names.append(str(like_prop).replace("=", " "))

    properties = _get_properties_to_include(property_names)

    # Look up the like-table's columns and determine which properties to transfer
    parent_table_query = t.cast(TableQuery, object_mapping.lookup_table_query(table=like_property.this))
    parent_columns = parent_table_query.get_column_defs()

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
                            message = f"Column '{inner_col.name}' does not exist in table '{child_object}'."
                            raise exception.SqlLeafException(message=message)

                        inner_col.set("catalog", exp.to_identifier(child_object.catalog))
                        inner_col.set("db", exp.to_identifier(child_object.db))
                        inner_col.set("table", exp.to_identifier(child_object.this))
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
        "DEFAULTS": {"include": False, "expr": exp.DefaultColumnConstraint},
        "GENERATED": {"include": False, "expr": exp.ComputedColumnConstraint},
        "IDENTITY": {"include": False, "expr": exp.GeneratedAsIdentityColumnConstraint},
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


def _process_unnamed(
    statement: exp.Expr, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q | None:
    """
    Process an unnamed statement - one not inside a 'CREATE <name>' statement.
    """
    query = None
    if isinstance(statement, exp.Insert):
        query = InsertQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    elif isinstance(statement, exp.Update):
        query = UpdateQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    elif isinstance(statement, exp.Merge):
        query = MergeQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    elif isinstance(statement, exp.Delete):
        query = DeleteQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
        if not statement.find(exp.Insert, exp.Update, exp.Merge):
            logging.warning(
                "Skipping statement: A DELETE query must have a data-modifying statement, "
                "such as an INSERT, to contain lineage."
            )
    elif isinstance(statement, exp.Select):
        if not statement.find(exp.Insert, exp.Update, exp.Merge, exp.Delete):
            logging.warning(
                "Skipping statement: A SELECT query must have a data-modifying statement, "
                "such as an INSERT, to contain lineage."
            )
        else:
            query = SelectQuery(
                expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
            )
    elif isinstance(statement, exp.Copy):
        query = CopyQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    elif isinstance(statement, exp.Put):
        query = PutQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )

    return query


def _process_tables(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q | None:
    """
    Process a 'CREATE TABLE' statement.
    """
    query: Q | None = None

    if statement.kind == "TABLE":
        # CREATE TABLE ...
        query = TableQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
        _set_column_defs(query)
        object_mapping.add_table_query(
            query=query,
            column_mapping=query.get_column_names_with_types(include_system=True),
        )
    elif statement.kind == "SEQUENCE":
        query = SequenceQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
        object_mapping.add_sequence_query(query=query)

    return query


def _process_views_and_ctas(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    """
    Convert a series of `CREATE VIEW/TABLE AS ...` SQL DDL statements into sqlglot's MappingSchema
    to extract the table and column details.
    """
    _unnest_values_inside_select(statement)

    # Expand any stars into column names so that they can be tracked in the mapping
    stmt = qualify(
        statement,
        schema=object_mapping,
        expand_stars=True,
        expand_alias_refs=False,
        qualify_columns=True,
        infer_schema=False,
        dialect=dialect,
        isolate_tables=False,
        validate_qualify_columns=False,
        quote_identifiers=False,
    )

    # Rename the aliases automatically added by sqlglot
    if not isinstance(stmt.expression, exp.Values):
        named_columns = stmt.args["this"].expressions
        for i, ins in enumerate(named_columns):
            # Overwrite the aliases because sqlglot may have added incorrect ones
            stmt.selects[i] = stmt.selects[i].as_(ins)

    # Add types from the mapping if available. Views often have unknown column types.
    stmt = annotate_types(stmt, dialect=dialect, schema=object_mapping)

    col_defs = _determine_column_defs(stmt, object_mapping)

    if stmt.kind == "VIEW":
        # CREATE VIEW ...
        query = ViewQuery(
            expr=stmt,
            dialect=dialect,
            object_mapping=object_mapping,
            columns=col_defs,
            statement_index=statement_index,
        )
    elif stmt.kind == "TABLE":
        # CREATE TABLE AS ...
        query = CTASQuery(
            expr=stmt,
            dialect=dialect,
            object_mapping=object_mapping,
            columns=col_defs,
            statement_index=statement_index,
        )
        query.system_column_defs = _system_columns(dialect=dialect)
    else:
        raise exception.SqlLeafException(message=f"Unhandled situation for query: {stmt.kind}")

    object_mapping.add_table_query(
        query=query,
        column_mapping=query.get_column_names_with_types(include_system=True),
    )
    return query


def _unnest_values_inside_select(statement: exp.Create):
    """
    Replace SELECT * FROM (VALUES ()) with VALUES ().
    This prevents sqlglot from assigning its own aliases.
    """
    # TODO: this should be done in a transform, checked against self.statement
    for values_expr in statement.find_all(exp.Values):
        parent = values_expr.parent_select
        while isinstance(parent, exp.Select) and parent.is_star and parent.parent_select:
            parent = parent.parent_select

        if parent and parent.parent:
            values_expr.pop()
            parent.parent.set("expression", values_expr)


def _determine_column_defs(statement: exp.Create, object_mapping: mappings.ObjectMapping) -> t.List[ColumnDef]:
    """
    Look up the columns for 'y' in 'INSERT INTO x TABLE y'
    """
    if isinstance(statement.expression, exp.Values):
        columns = [stmt.name for stmt in statement.this.expressions]
        types = [val.type for val in statement.expression.expressions[0].expressions]
        col_defs = [exp.ColumnDef(this=col_name, kind=col_type) for col_name, col_type in zip(columns, types)]
    else:
        col_defs = [exp.ColumnDef(this=exp.to_identifier(s.alias), kind=s.type) for s in statement.selects]

    return col_defs


def _process_functions(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    """
    Process a "CREATE FUNCTION" statement.
    """
    query = UserDefinedFunctionQuery(
        expr=statement,
        dialect=dialect,
        object_mapping=object_mapping,
        statement_index=statement_index,
    )
    object_mapping.add_udf_query(query, column_mapping=query.get_column_names_with_types(include_system=True))

    return query


def _process_triggers(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    """
    Process a "CREATE TRIGGER" statement.
    """
    query = TriggerQuery(statement, dialect, object_mapping, statement_index)
    object_mapping.add_type_query(query)
    return query


def _process_stored_procedures(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    """
    Process a "CREATE PROCEDURE" statement.
    """
    query = ProcedureQuery(
        expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
    )
    # object_mapping.add_query(kind="procedure", query=query, dialect=dialect)
    # TODO: find a way to get each SP's text from a query that has multiple SPs defined in it.
    #  sqlglot will parse the 2 SPs, but does not provide the original, raw text. This is imperfect
    #  as we would like to keep the original text for various reasons.
    # transformed_text = clean_stored_procedure_text(query.statement.sql())
    # query.text_transformed = transformed_text

    # The original text is lost, so we are forced to use the transformed text in its place for now
    # queries = collect_queries(text=transformed_text, dialect=dialect, object_mapping=object_mapping)
    # query.add_child_queries(child_queries=queries)
    return query


def _process_stage(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = StageQuery(statement, dialect, object_mapping=object_mapping, statement_index=statement_index)
    object_mapping.add_stage_query(query)
    return query


def _process_unload(
    statement: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = UnloadQuery(statement, dialect, object_mapping, statement_index)
    return query


def _process_type(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = TypeQuery(statement, dialect, object_mapping, statement_index)
    object_mapping.add_type_query(query)
    return query


def _process_schema(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = SchemaQuery(statement, dialect, object_mapping, statement_index)
    object_mapping.add_schema_query(query)
    return query


def _process_database(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = DatabaseQuery(statement, dialect, object_mapping, statement_index)
    object_mapping.add_database_query(query)
    return query
