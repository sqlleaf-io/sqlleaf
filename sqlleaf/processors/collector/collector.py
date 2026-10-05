import logging
import typing as t
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.normalize_identifiers import normalize_identifiers

from sqlleaf import exception, mappings, settings, typing, util
from sqlleaf.dialects.plpgsql import pgexp
from sqlleaf.models.query import (
    AssignmentQuery,
    BlockQuery,
    CallQuery,
    CopyQuery,
    CTASQuery,
    DatabaseQuery,
    DeleteQuery,
    ExecuteDynamicQuery,
    ExecuteQuery,
    FetchQuery,
    ForInQuery,
    InsertQuery,
    LoopQuery,
    MergeQuery,
    MultitableInsertQuery,
    OpenQuery,
    PerformQuery,
    PrepareQuery,
    ProcedureQuery,
    PutQuery,
    Q,
    QueryHolder,
    ReplaceQuery,
    SchemaQuery,
    SelectQuery,
    SequenceQuery,
    SetQuery,
    StageQuery,
    TableQuery,
    TriggerQuery,
    TypeQuery,
    UnloadQuery,
    UpdateQuery,
    UserDefinedFunctionQuery,
    ValuesQuery,
    ViewQuery,
    WhileQuery,
)
from sqlleaf.processors.collector import substitute
from sqlleaf.processors.collector.classify import _classify_command, _determine_query_kind
from sqlleaf.processors.transformer import transformer, udf
from sqlleaf.processors.transformer.expressions import simplify_row_in_values

logger = logging.getLogger("sqlleaf")

IMMEDIATE_TRANSFORM = (BlockQuery, ForInQuery, LoopQuery, OpenQuery, WhileQuery)

"""
Parses text for SQL statements and collects them into Query models.
"""


@dataclass(frozen=True)
class CollectQueryResult:
    queries: t.List[QueryHolder] = field(default_factory=list)  # Successfully processed, top-level queries
    unknown: t.Dict[str, int] = field(default_factory=dict)  # Unsupported by sqlleaf (no handler)
    unsupported: t.List[t.Tuple[int, exp.Expr]] = field(default_factory=list)  # Unsupported by sqlglot (no grammar)


def process_statement(
    statement: exp.Expr,
    dialect: str,
    object_mapping: mappings.ObjectMapping,
    statement_index: int | str,
    kind: str = "",
    parent_holder: QueryHolder = None,
) -> QueryHolder | None:
    """
    Classify, transform, and build a query holder for a single statement.
    """
    if not kind:
        if isinstance(statement, exp.Command):
            kind, supported = _classify_command(statement, dialect)
            if not kind or not supported:
                return None
        if not kind:
            statement, kind = _determine_query_kind(statement, dialect)

    if kind not in _QUERY_PROCESSORS:
        return None

    stmt = normalize_identifiers(statement, dialect=dialect, store_original_column_identifiers=True)
    stmt = _unnest_values_inside_select(stmt, dialect=dialect)

    if kind != "set" and object_mapping.session_variables:
        stmt = substitute.substitute_session_variables(stmt, object_mapping.session_variables)

    query: Q | None = _QUERY_PROCESSORS[kind](
        statement=stmt, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
    )
    if query is None:
        return None

    holder = QueryHolder(original=query)
    if parent_holder:
        parent_holder.add_downstream_holder(holder)

    if isinstance(query, IMMEDIATE_TRANSFORM):
        # Immediately transform queries inside a dynamic SQL block so that subsequent statements can used their values
        transformer.transform_query(holder)
        _collect_sequential_children(query, holder, dialect, object_mapping)
    else:
        _resolve_call_sites(query, holder, dialect, object_mapping)
        _collect_structural_children(query, holder, dialect, object_mapping)
        for child_holder in holder.get_all_holders():
            if child_holder.transformed is None:
                transformer.transform_query(child_holder)

    return holder


def _resolve_call_sites(
    query: Q,
    holder: QueryHolder,
    dialect: str,
    object_mapping: mappings.ObjectMapping,
) -> None:
    """
    Resolve and substitute function, procedure, or prepared statement call sites within a query.
    Extract child statements and inline user-defined functions into downstream query holders.
    """
    subst_statements: t.List[exp.Expr] = []
    if isinstance(query, CallQuery):
        subst_statements = substitute.substitute_call(query=query)
    elif isinstance(query, ExecuteQuery):
        subst_statements = substitute.substitute_execute(query=query)
    elif isinstance(query, ExecuteDynamicQuery):
        subst_statements = substitute.substitute_execute_dynamic(query=query)
    elif isinstance(query, CTASQuery) and query.source_info.type == typing.SqlObjectType.PREPARED_STATEMENT:
        subst_statements = [substitute.substitute_ctas_execute(query=query)]
    elif isinstance(query, UserDefinedFunctionQuery):
        return
    else:
        annotate_types(query.statement, dialect=dialect, schema=object_mapping)
        while True:
            node, matched_udf = udf.find_next_udf_call(query.statement, query.object_mapping)
            if not node:
                break

            # Check for any DML inner statements (e.g. INSERT ... VALUES ... RETURNING)
            raw_inner = matched_udf.inner_statements
            param_map, positional_map = substitute.transform_arguments(node, matched_udf)
            parent_index = query.get_statement_index()
            for idx, raw_stmt in enumerate(raw_inner):
                if isinstance(raw_stmt, (exp.Insert, exp.Update, exp.Delete, exp.Merge)) and raw_stmt.args.get(
                    "returning"
                ):
                    subst_dml = substitute.substitute_parameters(
                        raw_stmt.copy(), matched_udf, param_map, positional_map
                    )
                    process_statement(subst_dml, dialect, object_mapping, f"{parent_index}:{idx}", parent_holder=holder)

            target_node = udf.get_target_node(node)
            replacement_exprs = udf.build_replacement_exprs(node, matched_udf)
            if not replacement_exprs:
                break

            if len(replacement_exprs) > 1:
                udf.apply_replacement(target_node, replacement_exprs[-1], matched_udf)
            else:
                udf.apply_replacement(target_node, replacement_exprs[0], matched_udf)

    parent_index = query.get_statement_index()
    for i, stmt in enumerate(subst_statements):
        process_statement(stmt, dialect, object_mapping, f"{parent_index}:{i}", parent_holder=holder)


def _collect_sequential_children(
    query: Q, holder: QueryHolder, dialect: str, object_mapping: mappings.ObjectMapping
) -> None:
    """
    Collect queries inside a dynamic SQL block.
    This transforms queries as soon as they are discovered, allowing subsequent queries
    to use their results (e.g. variables/state).
    """
    if isinstance(query, (BlockQuery, ForInQuery, LoopQuery, WhileQuery)):
        object_mapping.push_variable_scope()

    if isinstance(query, BlockQuery):
        statement_idx = 0
        for item in query.declare_statements:
            process_statement(item, dialect, object_mapping, statement_idx, parent_holder=holder)
            statement_idx += 1

        for block_expr in query.inner_statements:
            process_statement(block_expr, dialect, object_mapping, statement_idx, parent_holder=holder)
            statement_idx += 1

    elif isinstance(query, ForInQuery):
        process_statement(query.statement.args["query"], dialect, object_mapping, 0, parent_holder=holder)

        for i, stmt in enumerate(query.inner_statements):
            process_statement(stmt, dialect, object_mapping, i + 1, parent_holder=holder)

    elif isinstance(query, OpenQuery):
        if query_expr := query.statement.args.get("expression"):
            process_statement(query_expr, dialect, object_mapping, 0, parent_holder=holder)

    elif isinstance(query, (LoopQuery, WhileQuery)):
        for i, stmt in enumerate(query.inner_statements):
            process_statement(stmt, dialect, object_mapping, i + 1, parent_holder=holder)

    if isinstance(query, (BlockQuery, ForInQuery, LoopQuery, WhileQuery)):
        object_mapping.pop_variable_scope()


def _collect_structural_children(
    query: Q, holder: QueryHolder, dialect: str, object_mapping: mappings.ObjectMapping
) -> None:
    """
    Collect 'structural' children of a query. These are purely structural decompositions of an
    already-parsed statement, such as a MERGE's child INSERT/UPDATE statements, or a CTE with an INSERT.
    """
    if isinstance(query, InsertQuery):
        _collect_insert_children(query, holder, object_mapping)
    elif isinstance(query, MergeQuery):
        _collect_merge_children(query, holder, object_mapping)
    elif isinstance(query, MultitableInsertQuery):
        _collect_multitable_insert_children(query, holder, object_mapping)

    if not isinstance(query, (CopyQuery, PutQuery)):
        _collect_writable_cte_queries(query, holder, dialect, object_mapping)

    for child_holder in list(holder.downstream_holders):
        _collect_structural_children(child_holder.original, child_holder, dialect, object_mapping)


def collect_queries(text: str, dialect: str, object_mapping: mappings.ObjectMapping) -> CollectQueryResult:
    """
    Parse a series of SQL statements provided as text.
    This includes tables, views, procedures, functions, sequences, etc.

    Each query may contain multiple child queries. For example, a stored procedure often
    has multiple individual queries; or a MERGE query has INSERTs or UPDATEs in its WHEN clauses.

    The statements must be provided in the order in which they depend on each other.
    If B depends on A, A must be created before B.
    """
    queries: t.List[QueryHolder] = []
    unknown: t.Dict[str, int] = {}
    unsupported: t.List[t.Tuple[int, exp.Expr]] = []

    parsed = _split_combined_statements(sqlglot.parse(text, dialect=dialect))
    for index, stmt in enumerate(parsed):
        if not stmt:
            continue

        kind = ""
        if isinstance(stmt, exp.Command):
            kind, supported = _classify_command(stmt, dialect)
            if not kind:
                logger.warning(f"Unsupported statement: {stmt.sql(dialect=dialect)}")
                unsupported.append((index, stmt))
                continue
            if not supported:
                unsupported.append((index, stmt))
                continue

        if not kind:
            stmt, kind = _determine_query_kind(stmt, dialect)

        if kind not in _QUERY_PROCESSORS:
            unknown[kind] = unknown[kind] + 1 if kind in unknown else 1
            continue

        holder = process_statement(stmt, dialect, object_mapping, statement_index=index, kind=kind)
        if holder is not None:
            queries.append(holder)

    return CollectQueryResult(queries=queries, unknown=unknown, unsupported=unsupported)


def _collect_writable_cte_queries(
    parent_query: Q, parent_holder: QueryHolder, dialect: str, object_mapping: mappings.ObjectMapping
) -> None:
    """
    Collect any writable (DML) CTEs and attach them as downstream holders to the parent query.

    If this query is of the form:
        WITH cte AS (
            INSERT ... RETURNING ...
        )
        INSERT INTO ...

    then the outer and inner queries form a parent-child relationship.
    The inner query is left as-is and copied, while the outer query transformer its
    inner query's SELECT columns with the RETURNING columns. This is so that
    the lineage functions collect the right columns during expression traversal.
    The two queries are processed independently later.
    """
    for i, cte in enumerate(parent_query.get_ctes()):
        cte_expr = cte.this

        if isinstance(cte_expr, (exp.Select, exp.Union)):
            continue

        query = _process_unnamed(cte_expr, dialect, object_mapping, i)
        # Detach the query in the AST so that certain transformations work later
        downstream_holder = QueryHolder(original=query)
        parent_holder.add_downstream_holder(downstream_holder)


def _collect_insert_children(
    query: InsertQuery, parent_holder: QueryHolder, object_mapping: mappings.ObjectMapping
) -> None:
    """
    Collect any additional queries inside an INSERT. For Postgres, this is 'INSERT .. ON CONFLICT DO UPDATE'.
    """
    if not isinstance(query.statement, exp.Insert):
        return

    on_conflict = query.statement.args.get("conflict")

    if not isinstance(on_conflict, exp.OnConflict) or on_conflict.args["action"].name == "DO NOTHING":
        return

    update_query = UpdateQuery(
        expr=on_conflict,
        dialect=query.dialect,
        object_mapping=object_mapping,
        statement_index=0,
        table=query.get_target_as_table(),
    )
    downstream_holder = QueryHolder(original=update_query)
    parent_holder.add_downstream_holder(downstream_holder)


def _collect_merge_children(
    parent_query: MergeQuery, parent_holder: QueryHolder, object_mapping: mappings.ObjectMapping
) -> None:
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
            downstream_holder = QueryHolder(original=update_query)
            parent_holder.add_downstream_holder(downstream_holder)

        elif isinstance(when_expr, exp.Insert):
            insert_query = InsertQuery(
                expr=when_expr,
                dialect=parent_query.dialect,
                object_mapping=object_mapping,
                statement_index=i,
                table=merge.get_target_as_table(),
            )
            insert_query.target_info = merge.target_info
            downstream_holder = QueryHolder(original=insert_query)
            parent_holder.add_downstream_holder(downstream_holder)


def _collect_multitable_insert_children(
    parent_query: MultitableInsertQuery, parent_holder: QueryHolder, object_mapping: mappings.ObjectMapping
) -> None:
    """
    Extract the ConditionalInsert (exp.Insert) branches from a Multitable INSERT statement.
    """
    statement = parent_query.statement
    for i, branch in enumerate(statement.expressions):
        if not isinstance(branch, exp.ConditionalInsert):
            continue

        insert_expr = branch.this
        if not isinstance(insert_expr, exp.Insert):
            continue

        copied_expr = util.copy_expression(insert_expr)

        if not copied_expr.expression and not copied_expr.args.get("source"):
            # If the branch doesn't have its own source, use the parent's shared source.
            # This happens in Snowflake multi-table inserts without explicit VALUES.
            copied_expr.set("expression", parent_query.source_info.expression)

        child_query = InsertQuery(
            expr=copied_expr,
            dialect=parent_query.dialect,
            object_mapping=object_mapping,
            statement_index=i,
        )
        downstream_holder = QueryHolder(original=child_query)
        parent_holder.add_downstream_holder(downstream_holder)


_UNNAMED_TYPE_MAP: dict[type, type] = {
    exp.Insert: InsertQuery,
    exp.Update: UpdateQuery,
    exp.Merge: MergeQuery,
    exp.MultitableInserts: MultitableInsertQuery,
    exp.Delete: DeleteQuery,
    exp.Select: SelectQuery,
    exp.Copy: CopyQuery,
    exp.Values: ValuesQuery,
    exp.Put: PutQuery,
    exp.Set: SetQuery,
    # PL/pgSQL
    pgexp.PGBlock: BlockQuery,
    pgexp.PGDeclareItem: AssignmentQuery,
    pgexp.PGFetch: FetchQuery,
    pgexp.PGForIn: ForInQuery,
    pgexp.PGOpen: OpenQuery,
    pgexp.PGPerform: PerformQuery,
    pgexp.PGExecute: ExecuteDynamicQuery,
    pgexp.PGLoop: LoopQuery,
    exp.PropertyEQ: AssignmentQuery,
    exp.WhileBlock: WhileQuery,
}


def _process_unnamed(
    statement: exp.Expr, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int | str
) -> Q:
    """
    Process an unnamed statement - one not inside a 'CREATE <name>' statement.
    """
    query_class = _UNNAMED_TYPE_MAP.get(type(statement))
    if query_class is not None:
        query = query_class(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
        if isinstance(query, DeleteQuery) and not statement.find(exp.Insert, exp.Update, exp.Merge):
            logger.warning(
                "Skipping statement: A DELETE query must have a data-modifying statement, "
                "such as an INSERT, to contain lineage."
            )
        return query

    if isinstance(statement, exp.Command) and statement.this.upper() == "CALL":
        return CallQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    if isinstance(statement, exp.Command) and statement.this.upper() == "EXECUTE":
        return ExecuteQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
    if isinstance(statement, exp.Create):
        if statement.kind == "TABLE":
            if isinstance(statement.expression, (exp.Select, exp.Values)) or statement.find(exp.ExecuteAsProperty):
                return _process_views_and_ctas(statement, dialect, object_mapping, statement_index)
            else:
                return _process_tables(statement, dialect, object_mapping, statement_index)
        elif statement.kind == "VIEW":
            return _process_views_and_ctas(statement, dialect, object_mapping, statement_index)

    raise exception.UnsupportedFeatureError(f"Statement of type '{type(statement)}' does not have a collector.")


def _process_tables(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int | str
) -> TableQuery | SequenceQuery | None:
    """
    Process a 'CREATE TABLE' statement.
    """
    query = None

    if statement.kind == "TABLE":
        # CREATE TABLE ...
        query = TableQuery(
            expr=statement, dialect=dialect, object_mapping=object_mapping, statement_index=statement_index
        )
        query.set_column_defs()
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
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int | str
) -> Q:
    """
    Convert a series of `CREATE VIEW/TABLE AS ...` SQL DDL statements into sqlglot's MappingSchema
    to extract the table and column details.
    """
    util.qualify_and_annotate(statement, dialect, object_mapping, remove_added_aliases=True)
    col_defs = _determine_column_defs(statement, dialect, object_mapping)

    if statement.kind == "VIEW":
        # CREATE VIEW ...
        query = ViewQuery(
            expr=statement,
            dialect=dialect,
            object_mapping=object_mapping,
            columns=col_defs,
            statement_index=statement_index,
        )
    elif statement.kind == "TABLE":
        # CREATE TABLE AS ...
        query = CTASQuery(
            expr=statement,
            dialect=dialect,
            object_mapping=object_mapping,
            columns=col_defs,
            statement_index=statement_index,
        )
        query.system_column_defs = settings.system_columns(dialect)
    else:
        raise exception.UnsupportedFeatureError(message=f"Unhandled situation for query: {statement.kind}")

    object_mapping.add_table_query(
        query=query,
        column_mapping=query.get_column_names_with_types(include_system=True),
    )
    return query


def _unnest_values_inside_select(statement: exp.Create, dialect: str):
    """
    Replace `SELECT * FROM (VALUES ())` with `VALUES ()`.
    This prevents sqlglot from assigning its own aliases.
    """
    # TODO: this should be done in a transform, checked against self.statement
    for values_expr in statement.find_all(exp.Values):
        simplify_row_in_values(values_expr, dialect)
        parent = values_expr.parent_select
        while isinstance(parent, exp.Select) and parent.is_star and parent.parent_select:
            parent = parent.parent_select

        if parent and parent.parent:
            # sqlglot converts "SELECT UNION VALUES" into "SELECT UNION SELECT * FROM (VALUES ()) AS _values"
            # We undo that transformation (risky, as actual query may have that alias)
            if alias := values_expr.args["alias"]:
                if alias.name != "_values":
                    return statement
                alias.pop()
            parent.replace(values_expr)

    return statement


def _determine_column_defs(
    statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping
) -> t.List[exp.ColumnDef]:
    """
    Look up the columns for 'y' in 'INSERT INTO x TABLE y'
    """
    if isinstance(statement.expression, exp.Values):
        # CREATE TABLE AS VALUES
        columns = [stmt.name for stmt in statement.this.expressions]
        types = [val.type for val in statement.expression.expressions[0].expressions]

        if not columns:
            columns = util.default_column_index_iterator(dialect, types)

        col_defs = [exp.ColumnDef(this=col_name, kind=col_type) for col_name, col_type in zip(columns, types)]
    elif exec_prop := statement.find(exp.ExecuteAsProperty):
        # CREATE TABLE AS EXECUTE
        plan_name = exec_prop.this.name
        plan_table = exp.to_table(plan_name)
        matched_prepare = object_mapping.lookup_prepare_query(plan_table, raise_on_missing=True)

        source = matched_prepare.statement
        if isinstance(source, exp.Select):
            col_defs = [
                exp.ColumnDef(this=exp.to_identifier(col.alias_or_name), kind=col.unalias().type)
                for col in source.expressions
            ]
        else:
            col_defs = []
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
    object_mapping.add_trigger_query(query)
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
    object_mapping.add_procedure_query(query)
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


def _process_replace(
    statement: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = ReplaceQuery(statement, dialect, object_mapping, statement_index)
    return query


def _process_prepare(
    statement: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = PrepareQuery(statement, dialect, object_mapping, statement_index)
    object_mapping.add_prepare_query(query)
    return query


def _process_execute(
    statement: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
) -> Q:
    query = ExecuteQuery(statement, dialect, object_mapping, statement_index)
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

# TODO: if not in list, use '_process_unnamed'
_QUERY_PROCESSORS: dict[str, t.Callable] = {
    "table": _process_tables,
    "ctas": _process_views_and_ctas,
    "view": _process_views_and_ctas,
    "sequence": _process_tables,
    "procedure": _process_stored_procedures,
    "multitableinserts": _process_unnamed,
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
    "replace": _process_replace,
    "prepare": _process_prepare,
    "execute": _process_execute,
    "stage": _process_stage,
    "call": _process_unnamed,
    "copy": _process_unnamed,
    "put": _process_unnamed,
    "set": _process_unnamed,
    "values": _process_unnamed,
    "type": _process_type,
    "pgblock": _process_unnamed,
    "pgdeclareitem": _process_unnamed,
    "pgfetch": _process_unnamed,
    "pgforin": _process_unnamed,
    "pgloop": _process_unnamed,
    "pgopen": _process_unnamed,
    "pgperform": _process_unnamed,
    "pgexecute": _process_unnamed,
    "propertyeq": _process_unnamed,
}


def _split_combined_statements(parsed: t.List[exp.Expr]) -> t.List[exp.Expr]:
    """
    Workaround for sqlglot incorrectly bundling statements following a block-based CREATE.
    For example, with the statement "CREATE PROCEDURE .. BEGIN .. END; CALL();" the CALL()
    is included with the procedure definition.
    """
    new_parsed = []
    for stmt in parsed:
        if isinstance(stmt, exp.Create) and isinstance(stmt.args.get("expression"), exp.Block):
            block = stmt.args["expression"]
            end_index = -1
            for i, expr in enumerate(block.expressions):
                if isinstance(expr, exp.EndStatement):
                    end_index = i
                    break

            # Separate the statements
            if end_index != -1 and end_index < len(block.expressions) - 1:
                extra = block.expressions[end_index + 1 :]
                block.set("expressions", block.expressions[: end_index + 1])
                new_parsed.append(stmt)
                new_parsed.extend(extra)
                continue

        new_parsed.append(stmt)
    return new_parsed
