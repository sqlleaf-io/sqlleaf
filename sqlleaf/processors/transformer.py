import typing as t
import logging
import copy

import sqlglot
from sqlglot import exp
from sqlglot.optimizer import optimize, qualify, RULES
from sqlglot.optimizer.merge_subqueries import merge_derived_tables

from sqlleaf import exception, mappings, util
from sqlleaf.objects.query_types import CopyQuery, UpdateQuery, InsertQuery, MergeQuery, Query

logger = logging.getLogger("sqleaf")


def transform_query(query: Query, object_mapping: mappings.ObjectMapping):
    """
    Transform a query's expression according to rules specific to its type.
    """
    logger.debug(f"Transforming - Query: {query.__class__.__name__}, Statement: {query.statement.__class__.__name__}")
    statement = util.copy_expression(query.statement)

    if isinstance(query, InsertQuery):
        statement = _convert_defaults_to_values(statement, object_mapping, query.child_table)
        statement = _convert_insert_values_to_select(statement, object_mapping, query.child_table)
        statement = _add_information_from_merge(statement, query)
        statement = _process_inner_ctes(statement, query, object_mapping)

    elif isinstance(query, UpdateQuery):
        statement = _add_information_from_merge(statement, query)
        statement = _convert_update_to_insert(statement, query.dialect)
        statement = _process_inner_ctes(statement, query, object_mapping)

    elif isinstance(query, MergeQuery):
        statement = _process_inner_ctes(statement, query, object_mapping)

    elif isinstance(query, CopyQuery):
        statement = _convert_copy_to_insert(statement, query, object_mapping)

    # Apply sqlglot's optimize() functions to infer schemas, qualify columns, etc
    statement = _apply_optimizations(statement, query.dialect, object_mapping, query.child_table)

    # Transform CASE statements to remove false positive lineage; see docs
    statement = statement.transform(_case_statement_transformer)

    logger.debug(f"Transformed {str(type(statement))}: {statement.sql(dialect=query.dialect)}")
    query.statement_transformed = statement
    query.set_statement(statement)


def _process_inner_ctes(statement: exp.Insert | exp.Merge | exp.Update, query: Query, object_mapping: mappings.ObjectMapping) -> exp.Insert | exp.Merge | exp.Update:
    """
    Transform any inner CTE statements.
    """
    for cte_expr in getattr(statement, 'ctes', []):
        if isinstance(cte_expr.this, exp.Update):
            # Replace the inner UPDATE with an INSERT first.
            # The inner query is different from the child query, which is its own separate copy.
            inner_expr = _convert_update_to_insert(statement=cte_expr.this, dialect=query.dialect)
            cte_expr.this.replace(inner_expr)

        # Rename the columns and replace the INSERT with the SELECT
        _rename_returning_columns(expr=cte_expr, dialect=query.dialect, object_mapping=object_mapping, child_table=cte_expr.find(exp.Table))
        # cte_expr.set("this", select_expr)

    return statement


def _convert_insert_values_to_select(statement: exp.Insert, object_mapping: mappings.ObjectMapping, child_table: exp.Table) -> exp.Insert:
    """
    Transform an
        INSERT INTO x VALUES (...)
    into an
        INSERT INTO x SELECT ...
    so that the lineage functions can process it.

    We don't attempt to add the column names from the mapping as we may have
    stars in the columns. This comes later.
    """
    if isinstance(statement.expression, exp.Values):
        values = statement.expression.expressions[0].expressions
        columns = [e.name for e in statement.this.expressions]

        if not columns:
            cols = object_mapping.find_columns_for_table(child_table)
            columns = list(cols)[:len(values)]

        selects = [exp.alias_(val, str(col)) for col, val in zip(columns, values)]
        new_select = exp.select(*selects)
        insert_expr = exp.insert(
            expression=new_select,
            columns=statement.this.expressions,
            into=child_table,
        )
        statement.replace(insert_expr)
        return insert_expr
    return statement


def _convert_defaults_to_values(statement: exp.Insert, object_mapping: mappings.ObjectMapping, child_table: exp.Table) -> exp.Insert:
    """
    Transform the query:
        INSERT INTO x (name, age) VALUES (DEFAULT, DEFAULT);
    into its default values (as defined in its table):
        INSERT INTO x (name, age) VALUES (NULL, 42);
    """
    values = statement.expression
    if not isinstance(values, exp.Values):
        return statement

    columns = statement.this.expressions

    for value_expr in values.expressions:
        if isinstance(value_expr, exp.Tuple):
            for i, tuple_expr in enumerate(value_expr.expressions):
                if isinstance(tuple_expr, exp.Var) and tuple_expr.name.upper() == 'DEFAULT':
                    # Replace 'DEFAULT' with the associated column's default expression
                    table_query = object_mapping.find_query(kind='table', table=child_table)
                    col_def = [col for col in table_query.get_column_defs() if col.name == columns[i].name][0]

                    if default_expr := col_def.find(exp.DefaultColumnConstraint):
                        tuple_expr.replace(default_expr.this)
                    else:
                        tuple_expr.replace(exp.Null())

    return statement


def _convert_update_to_insert(statement: exp.Update, dialect: str) -> exp.Insert:
    """
    Taken from function extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

    This transforms an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.
    """
    _UPDATE_FROM_TABLE_ARGS_TO_MOVE = {"joins", "laterals", "pivot"}
    _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT: t.Set[str] = set(exp.Update.arg_types.keys()) - set(exp.Select.arg_types.keys())

    if where := statement.args.get('where', None):
        # WHERE statements aren't relevant to lineage
        where.pop()

    # The "SET" expressions need to be converted.
    # For the update command, it'll be a list of EQ expressions, but the select
    # should contain aliased columns.
    alias_names = []
    new_expressions = []
    for expr in statement.expressions:
        if isinstance(expr, exp.EQ) and isinstance(expr.left, exp.Column):
            alias_names.append(expr.left.this)
            new_expressions.append(
                exp.Alias(
                    this=expr.right,
                    alias=expr.left.this,
                )
            )
        else:
            # If we don't know how to convert it, just leave it as-is. If this causes issues,
            # they'll get caught later.
            new_expressions.append(expr)

    # Special translation for the `from` clause.
    extra_args: dict = {}
    original_from = statement.args.get("from")
    if original_from and isinstance(original_from.this, exp.Table):
        # Move joins, laterals, and pivots from the Update->From->Table->field
        # to the top-level Select->field.

        for k in _UPDATE_FROM_TABLE_ARGS_TO_MOVE:
            if k in original_from.this.args:
                # Mutate the from table clause in-place.
                extra_args[k] = original_from.this.args.get(k)
                original_from.this.set(k, None)

    # We need to add the CTEs to the insert, not as part of the select.
    # Otherwise the query will be ordered incorrectly (i.e. INSERT .. WITH () .. SELECT)
    with_ = statement.args.get("with_", None)
    if with_:
        with_.pop()

    select_statement = exp.Select(
        **{
            **{k: v for k, v in statement.args.items() if k not in _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT},
            **extra_args,
            "expressions": new_expressions,
        }
    )

    # Convert the statement into an insert
    insert_statement = exp.insert(
        expression=select_statement,
        columns=alias_names,
        into=util.get_table(statement),
        returning=statement.args.get('returning', None),
        dialect=dialect,
    )
    if with_:
        insert_statement.set('with_', with_)

    statement.replace(insert_statement)
    return insert_statement


def _add_information_from_merge(statement: exp.Insert | exp.Update, query: InsertQuery | UpdateQuery) -> exp.Insert | exp.Update:
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
    # TODO: what if we're inside a WITH ( UPDATE ) MERGE ? Shouldn't run
    merge_expr = statement.find_ancestor(exp.Merge)
    if not merge_expr:
        return statement

    using = merge_expr.args["using"]
    on = merge_expr.args["on"]
    returning = merge_expr.args.get("returning", None)

    if "with_" in merge_expr.args:
        ctes = merge_expr.args["with_"].expressions
    else:
        ctes = []

    new_ctes = [
        {
            "alias": cte.alias_or_name,
            "as_": cte.this.sql(),
        }
        for cte in ctes
    ]

    if isinstance(statement, exp.Update):
        # Add the missing information to the UPDATE statement
        query.only = query.child_table.args.get('only', False)
        update_expr = statement.table(query.child_table).from_(using).where(on)
        update_expr.set('returning', returning)

        for cte in new_ctes:
            update_expr = update_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(update_expr)
        return update_expr


    elif isinstance(statement, exp.Insert):
        # Add the missing information to the INSERT statement
        new_columns = statement.expression.expressions
        new_aliases = statement.this.expressions

        aliases = [exp.alias_(str(col), str(alias)) for col, alias in zip(new_columns, new_aliases)]

        # Build a new SELECT
        new_select = exp.select(*aliases).from_(using)

        insert_expr = exp.insert(
            expression=new_select,
            columns=[col.this for col in statement.this.expressions],
            into=query.child_table,
            dialect=query.dialect,
            returning=returning,
        )

        for cte in new_ctes:
            insert_expr = insert_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(insert_expr)
        return insert_expr

    return statement


def _convert_copy_to_insert(statement: exp.Copy, query: CopyQuery, object_mapping) -> exp.Insert:
    """
    Convert the COPY statement into an INSERT statement so that the lineage functions can process it.

    COPY INTO <table> FROM @stage
        -> INSERT INTO <table> SELECT * FROM @stage
        => is_source_a_stage = True
        => produces lineage: @stage -> N table columns
    COPY INTO @stage FROM <table>
        -> INSERT INTO @stage SELECT * FROM <table>
        => is_target_a_stage = True
        => produces lineage: N table columns -> @stage
    """
    expr = statement
    dialect = query.dialect

    if query.is_source_a_stage:
        child_table = expr.this
        parent_table = expr.args['files'][0]
        source_table = child_table
    elif query.is_target_a_stage:
        child_table = expr.this
        parent_table = expr.args['files'][0]
        source_table = parent_table

    child_columns = object_mapping.find_columns_for_table(table=source_table)
    column_names = tuple(child_columns.keys())

    # Convert the Copy to an Insert so that the lineage functions work
    select = exp.select(*column_names, dialect=dialect).from_(parent_table)
    expr_insert = exp.insert(
        expression=select,
        into=child_table,
        dialect=dialect,
    )

    if query.is_target_a_stage:
        # Any object that is referenced as a source table needs to be added to the table mapping
        # for the lineage functions to work - such as this Stage
        col_defs = [exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(type)) for name, type in child_columns.items()]

        child_table_query = object_mapping.find_query(kind='stage', table=child_table)
        child_table_query.column_defs = col_defs

    # We don't worry about `self.is_source_a_stage` here as that is handled in the process_column() later
    statement.replace(expr_insert)
    return expr_insert


RULES_OVERRIDE = [
    r for r in RULES if r.__name__ not in [
        'eliminate_ctes',       # Preserve CTEs
        'merge_subqueries',     # Preserve CTEs
        'qualify',              # We qualify when we need to
        'quote_identifiers',    # Preserve identifiers
    ]
]


def _apply_optimizations(statement: exp.Insert, dialect: str, object_mapping: mappings.ObjectMapping, child_table, match_columns: bool = True) -> exp.Insert :
    """
    1. We pass validate=false to prevent errors like: sqlglot.errors.OptimizeError: Column '"v_ca_start_date_id"' could not be resolved
    2. We pass infer_schema=True to source unqualified columns from the source table (if missing from the `schema` param)
        e.g. so that
            INSERT INTO my.other
            SELECT name
            FROM my.table
        produces
            my.table.name -> my.other.name
    """
    # Rewrite the columns in any child writable CTEs.
    # We cannot rely on lineage() to collect the RETURNING statements
    # due to limitations with the optimizer.build_scope function: it only
    # considers select statements.
    stmt = qualify.qualify(
        statement,
        schema=object_mapping,
        infer_schema=True,
        dialect=dialect,
        isolate_tables=False,
        validate_qualify_columns=False,
        quote_identifiers=False,
    )

    if match_columns:
        _add_column_names_to_insert(stmt, object_mapping, child_table)

    # Selectively apply sqlglot's optimization rules.
    stmt = optimize(expression=stmt, dialect=dialect, schema=object_mapping, rules=RULES_OVERRIDE)
    stmt = merge_derived_tables(stmt)   # Skip merge_ctes()

    return stmt


def _rename_returning_columns(expr: exp.CTE, dialect: str, object_mapping: mappings.ObjectMapping, child_table: exp.Table):
    """
    Given an (INSERT .. RETURNING *) statement, expand the star to the table's column names
    and add the correct column aliases.

    For example, the query:
        INSERT INTO fruit.raw (name)
        SELECT 'orange' AS name
        RETURNING UPPER(name)

    is rewritten to:
        SELECT UPPER(name)
        FROM fruit.raw

    Note that:
    MERGE RETURNING * returns all columns from source and target
    UPDATE RETURNING * returns all columns from target
    INSERT RETURNING * returns all columns from target
    DELETE RETURNING * returns all columns from target
    """
    returning_expr: exp.Returning = expr.this.args.get('returning', None)
    if not returning_expr:
        return expr

    for col_expr in returning_expr.expressions:
        if not isinstance(col_expr, (exp.Alias, exp.Column, exp.Star)):
            message = f"Non-column expression ({col_expr}) must have an alias inside RETURNING to prevent ambiguity."
            raise exception.SqlLeafException(message=message)

    # Replace the OLD & NEW aliases with the table alias if it exists. Otherwise, remove it to be valid.
    returning_columns = list(returning_expr.find_all(exp.Column))
    for col in returning_columns:
        if col.table.lower() in ['old', 'new']:
            if child_table.alias:
                col.set('table', exp.to_identifier(child_table.alias, quoted=False))
            else:
                col.args['table'].pop()
                if isinstance(col.this, exp.Star):
                    # optimize() needs Star(), not Column(Star())
                    col.replace(col.this)

    if isinstance(expr.this, exp.Merge):
        using = expr.this.args['using']
        on = expr.this.args['on']
        new_select = exp.select(*returning_expr.expressions).from_(child_table).join(using, on=on)
    else:
        new_select = exp.select(*returning_expr.expressions).from_(child_table)

    new_select = _apply_optimizations(new_select, dialect, object_mapping, child_table, match_columns=False)

    expr.set("this", new_select)
    return expr


def _add_column_names_to_insert(statement: exp.Insert, object_mapping: mappings.ObjectMapping, child_table: exp.Table):
    """
    Add aliases to SELECTs that are missing them by looking at the corresponding INSERT column.
    This prevents sqlglot from assigning its own generated names as aliases.

    For example, the statement:
        INSERT INTO my.apple SELECT name, age FROM my.pear
    renames to:
        INSERT INTO my.apple (a,b) SELECT name as a, age as b FROM my.pear

    match_columns: whether the SELECT aliases should match the INSERT's columns
    """
    if not isinstance(statement, exp.Insert) or not statement.selects:
        return statement

    selects = statement.selects
    table_query = object_mapping.get_table_or_stage(child_table)
    table_columns = [c.name for c in table_query.get_column_defs()]

    insert_columns = []
    if isinstance(statement.this, exp.Schema):
        # INSERT INTO fruit.raw (name)
        insert_columns = [s.name for s in statement.this.expressions]
    elif isinstance(statement.this, exp.Table):
        # INSERT INTO fruit.raw AS r (name)
        insert_columns = [s for s in statement.this.alias_column_names]

    if not insert_columns:
        # Add the column names from the mapping to the query
        insert_columns = list(table_columns)[:len(selects)]
        schema = exp.Schema(this=child_table, expressions=[exp.to_identifier(c) for c in insert_columns])
        statement.set('this', schema)

    else:
        unknown_columns = [col for col in insert_columns if col not in table_columns]
        if unknown_columns:
            raise exception.SqlLeafException(
                message=f"Unknown columns used in SELECT: {list(unknown_columns)}",
                table=str(exp.table_name(child_table)),
            )

        if "*" in selects:
            raise exception.SqlLeafException(
                message="Statement has unresolved star column",
                table=str(exp.table_name(child_table)),
            )

        if len(insert_columns) != len(statement.selects):
            message = "Mismatched column count: number of column names (%s) does not match selected columns (%s)" % (
                len(insert_columns),
                len(statement.selects),
            )
            raise exception.SqlGlotException(message=message, table=child_table)

    aliases = [s.alias_or_name for s in statement.selects]
    if aliases != insert_columns:
        message = "Mismatched column names: column names (%s) do not match column aliases (%s)" % (
            ",".join(insert_columns),
            ",".join(aliases),
        )
        logger.warning(message)

    for i, ins in enumerate(insert_columns):
        # Overwrite the aliases because sqlglot may have added incorrect ones
        statement.selects[i] = statement.selects[i].as_(ins)


def _case_statement_transformer(expr: exp.Expression):
    """
    Transform the 'WHEN' part of every CASE statement so be 1=1 so that the lineage
    does not include the original columns in this clause.

    By default, sqlglot will include columns used in 'WHEN' to the lineage, but they're false positives.
    e.g.
        SELECT CASE WHEN age > 30 THEN 'y' ELSE 'n' END AS approved
    should produce lineage for 'y' and 'n', but not 'age'.

    But if we change it to
        SELECT CASE WHEN 1=1 THEN 'y' ELSE 'n' END AS approved
    then sqlglot will exclude it correctly.

    This is admittedly quite hacky, but it's the cleanest approach considering the limitations of sqlglot's Scope() and
    lineage() functions.
    """
    if isinstance(expr, exp.Case):
        case = exp.case()
        for _if in expr.args["ifs"]:
            try:
                case = case.when("'dummy'='value'", then=_if.args["true"])
                if "default" in expr.args:
                    case = case.else_(expr.args["default"])
            except Exception:
                pass
        return case
    return expr


def clean_stored_procedure_text(text: str) -> str:
    """
    Extract the queries from inside a stored procedure by removing any
    syntax/keywords that cannot be parsed by sqlglot.

    Parameters:
        text: text containing a stored procedure
    """
    logger.debug("Cleaning stored procedure text.")
    lines = text.splitlines()

    # Transform the procedure's text
    lines = remove_lines_before_begin(lines)
    lines = remove_lines_after_unsupported_syntax(lines)
    lines = remove_raise_statements(lines)

    return "\n".join(lines)


def remove_lines_before_begin(lines: t.List[str], comment=False) -> t.List[str]:
    """
    Remove every line until 'BEGIN', inclusive.

    Parameters:
        lines: list of strings representing a stored procedure
        comment: whether to comment out the matching lines instead of removing them
    """
    stripped_lines = [line.lower().strip() for line in lines]

    # Only process procedures that contain 'begin'
    if "begin" not in stripped_lines:
        return lines

    new_lines = copy.copy(lines)

    # Comment out every line until we reach 'begin'
    for i, line in enumerate(lines):
        l = line.lower().strip()
        if not l.startswith("--"):
            if comment:
                line = "-- " + line
            else:
                line = ""

        # Only overwrite/strip new lines
        new_lines[i] = line
        if l == "begin":
            break

    return new_lines


def remove_lines_after_unsupported_syntax(lines: t.List[str]) -> t.List[str]:
    """
    Remove every line on and after unsupported syntax (e.g. 'EXCEPTION', 'RETURN').

    Parameters:
        lines: list of strings representing a stored procedure
    """
    new_lines = []

    for i, line in enumerate(lines):
        if line.lower().strip().startswith(("exception", "return ")):
            break
        new_lines.append(line)

    return new_lines


def remove_raise_statements(lines: t.List[str]) -> t.List[str]:
    """
    Remove every line starting with 'RAISE'.

    Parameters:
        lines: list of strings representing a stored procedure
    """
    new_lines = []

    for i, line in enumerate(lines):
        if line.lower().strip().startswith("raise "):
            continue
        new_lines.append(line)

    return new_lines
