import functools
import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer import RULES, optimize, qualify
from sqlglot.optimizer.merge_subqueries import merge_derived_tables

from sqlleaf import exception, mappings, util
from sqlleaf.objects.query_types import (
    CopyQuery,
    CTASQuery,
    DeleteQuery,
    InsertQuery,
    MergeQuery,
    Q,
    TableQuery,
    UnloadQuery,
    UpdateQuery,
    UserDefinedFunctionQuery,
)
from sqlleaf.typing import E

logger = logging.getLogger("sqlleaf")

"""
Transform an SQL query into a form that we can easily generate the lineage from.
We transform all queries into `INSERT .. SELECT` where possible so that we have
a single query type to work over.
"""

# TODO: ensure columns have valid types after all transformations (only top-level SELECT for now)


def transform_query(query: Q, object_mapping: mappings.ObjectMapping) -> None:
    """
    Transform a query's expression according to rules specific to its type.
    """
    statement_to_transform = util.copy_expression(query.statement_original)
    statement_to_substitute = util.copy_expression(query.statement_original)

    transformed = _transform_statement(statement_to_transform, query, object_mapping)
    query.set_transformed_statement(transformed)

    statement_substituted = _get_substituted_statement(statement_to_substitute, query, object_mapping)
    if statement_substituted:
        substituted = _transform_statement(statement_substituted, query, object_mapping)
        query.set_substituted_statement(substituted)


def _get_substituted_statement(
    statement: exp.Expr, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.Expr | None:
    """
    Transform a statement by substituting all its UDF references with each UDF's underlying return expression.

    Returns a statement only if a UDF was substituted.
    """
    # TODO
    return None


def _transform_statement(statement: E, query: Q, object_mapping: mappings.ObjectMapping) -> exp.Expr:
    """
    Perform a series of transformations against an SQL statement.
    """
    logger.debug("----")
    logger.debug(f"Query: {statement.sql(dialect=query.dialect)}")
    logger.debug(f"Transforming: {query.__class__.__name__} - {statement.__class__}")

    statement = _convert_table_to_select(statement=statement, query=query, object_mapping=object_mapping)

    # Remove any FILTER or WHERE clauses
    for filter_expr in statement.find_all(exp.Filter):
        filter_expr.replace(filter_expr.this)

    for where_expr in statement.find_all(exp.Where):
        where_expr.pop()

    # TODO: Unpack dict for common args

    if isinstance(query, InsertQuery) and isinstance(statement, exp.Insert):
        statement = _convert_insert_defaults_to_values(statement=statement, query=query, object_mapping=object_mapping)
        if statement.expression:
            statement_converted = _convert_outer_values_to_select(
                expression=statement.expression, statement=statement, query=query, object_mapping=object_mapping
            )
            if isinstance(statement_converted, exp.Insert):
                statement = statement_converted

        statement = _add_information_from_merge(statement=statement, query=query, object_mapping=object_mapping)
        statement = _process_inner_ctes(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, UpdateQuery) and isinstance(statement, (exp.OnConflict, exp.Update)):
        statement = _convert_on_conflict_to_update(statement=statement, query=query, object_mapping=object_mapping)
        if isinstance(statement, (exp.Insert, exp.Update)):
            statement = _add_information_from_merge(statement=statement, query=query, object_mapping=object_mapping)
        if isinstance(statement, exp.Update):
            statement = _convert_update_defaults_to_values(
                statement=statement, query=query, object_mapping=object_mapping
            )
            statement = _convert_update_to_insert(statement=statement, query=query, object_mapping=object_mapping)
        if isinstance(statement, (exp.Insert, exp.Merge, exp.Update, exp.Delete)):
            statement = _process_inner_ctes(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, MergeQuery) and isinstance(statement, exp.Merge):
        statement = _process_inner_ctes(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, DeleteQuery) and isinstance(statement, exp.Delete):
        statement = _process_inner_ctes(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, CopyQuery) and isinstance(statement, exp.Copy):
        statement = _convert_copy_to_insert(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, UnloadQuery) and isinstance(statement, exp.Select):
        statement = _convert_unload_to_insert(statement=statement, query=query, object_mapping=object_mapping)

    elif isinstance(query, CTASQuery) and isinstance(statement, exp.Create):
        if statement.expression:
            statement_converted = _convert_outer_values_to_select(
                statement.expression, statement=statement, query=query, object_mapping=object_mapping
            )
            if isinstance(statement_converted, exp.Create):
                statement = statement_converted

    elif isinstance(query, TableQuery):
        pass

    if isinstance(statement, exp.Insert):
        _validate_values(statement=statement, query=query, object_mapping=object_mapping)

    # Qualify columns, add aliases and optimize the expressions
    statement = _apply_optimizations(statement=statement, query=query, object_mapping=object_mapping)

    # Validate syntax manually here as the last step
    try:
        sqlglot.parse_one(statement.sql(dialect=query.dialect), dialect=query.dialect)
    except sqlglot.errors.ParseError:
        if query.dialect == "redshift" and isinstance(query, TableQuery) and query.property == "external":
            # Bug in sqlglot: parsing the output for CREATE EXTERNAL TABLE WITH (FORMAT=TEXTFILE) breaks the parser
            pass

    old = query.statement.sql(dialect=query.dialect)
    new = statement.sql(dialect=query.dialect)
    if old == new:
        logger.debug("No transformations applied.")
    else:
        logger.debug(f"Transformed {type(statement).__name__}: {new}")

    return statement


def _validate_syntax(func):
    """
    Ensure that the transformed query is parseable.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> E:
        statement = kwargs.pop("statement")
        query = kwargs.pop("query")
        object_mapping = kwargs.pop("object_mapping")

        result = func(statement=statement, query=query, object_mapping=object_mapping, *args, **kwargs)

        if result and (statement.sql(dialect=query.dialect) != result.sql(dialect=query.dialect)):
            logger.debug(f"Transformed by {func}.")

        if result is None:
            return result

        try:
            sqlglot.parse_one(result.sql(dialect=query.dialect), dialect=query.dialect)
        except sqlglot.errors.ParseError:
            if query.dialect == "redshift" and isinstance(query, TableQuery) and query.property == "external":
                # Bug in sqlglot: parsing the output for CREATE EXTERNAL TABLE WITH (FORMAT=TEXTFILE) breaks the parser
                pass

        return result

    return wrapper


class Transformer:
    def __init__(self, statement: E, query: Q, object_mapping: mappings.ObjectMapping):
        self.statement = statement
        self.query = query
        self.object_mapping = object_mapping


@_validate_syntax
def _convert_table_to_select(statement: E, query: Q, object_mapping: mappings.ObjectMapping) -> E:
    """
    Convert the statement "TABLE x" to "SELECT * FROM x"
    """
    source = statement.args.get("source", None)
    if source:
        table = source.pop()
        statement.set("expression", exp.select("*").from_(table))
    return statement


@_validate_syntax
def _add_aliases_to_pseudocolumns(statement: exp.Expr, query: Q, object_mapping: mappings.ObjectMapping) -> None:
    """
    Given a query:
        SELECT xmax FROM fruit.raw
    rename it to:
        SELECT raw.xmax FROM fruit.raw
    or use the table's alias instead.

    This requires that the tables and columns have run through qualify()
    """
    for pseudo in statement.find_all(exp.Pseudocolumn):
        if pseudo.table:
            continue

        if pseudo.parent_select and pseudo.parent_select.args.get("from_"):
            from_table_alias = pseudo.parent_select.args["from_"].alias_or_name
            pseudo.set("table", exp.to_identifier(from_table_alias))


@_validate_syntax
def _process_inner_ctes(
    statement: exp.Insert | exp.Merge | exp.Update | exp.Delete, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.Insert | exp.Merge | exp.Update | exp.Delete:
    """
    Transform any inner CTE statements.
    """
    for cte_expr in getattr(statement, "ctes", []):
        if isinstance(cte_expr.this, exp.Update):
            # Replace the inner UPDATE with an INSERT first.
            # The inner query is different from the child query, which is its own separate copy.
            inner_expr = _convert_update_to_insert(statement=cte_expr.this, query=query, object_mapping=object_mapping)
            cte_expr.this.replace(inner_expr)

        elif cte_expr.this.is_star:
            # VALUES() has already been transformed into SELECT * FROM (VALUES())
            from_ = cte_expr.this.args["from_"].this

            if isinstance(from_, exp.Values):
                values_expr = _convert_cte_values_to_select(
                    expression=from_, statement=cte_expr, query=query, object_mapping=object_mapping
                )
                cte_expr.this.replace(values_expr)

        # Rename the columns and replace the INSERT with the SELECT
        _rename_returning_columns(
            statement=cte_expr, query=query, object_mapping=object_mapping, child_table=cte_expr.find(exp.Table)
        )

    return statement


@_validate_syntax
def _convert_cte_values_to_select(
    expression: exp.Values, statement: exp.CTE, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.CTE | exp.Insert | exp.Create:
    """
    Transform the query:
        WITH cte (age, name) AS (
            VALUES (1, 'apple'), (2, 'banana')
        )
    into:
        WITH cte (age, name) AS (
            SELECT 1, 'apple' UNION ALL SELECT 2, 'banana'
        )
    so that the lineage functions can process it using build_scope().
    """
    if not isinstance(expression, exp.Values):
        return statement

    columns = statement.alias_column_names
    if not columns:
        # Try and get the columns from the top-level insert
        columns = [e.name for e in statement.root().this.expressions]

    return _values_to_select_union(columns, expression, statement=statement, query=query, object_mapping=object_mapping)


@_validate_syntax
def _values_to_select_union(
    columns: t.List[str],
    expression: exp.Values,
    statement: exp.CTE | exp.Insert | exp.Create,
    query: Q,
    object_mapping: mappings.ObjectMapping,
) -> exp.CTE | exp.Insert | exp.Create:
    """
    Convert a VALUES(x, y) to a SELECT x UNION ALL SELECT y
    """
    values_lists: t.List[exp.Tuple] = expression.expressions
    child_table = query.get_target_as_table()

    if not columns:
        # Get the names from the mapping
        cols = object_mapping.find_columns_for_table(child_table)
        columns = list(cols)[: len(values_lists[0].expressions)]

    selects = []
    for val_list in values_lists:
        values = val_list.expressions
        cols = [exp.alias_(val, str(col)) for col, val in zip(columns, values)]
        selects.append(cols)

    if len(selects) > 1:
        new_selects = [exp.select(*select) for select in selects]
        new_statement = exp.union(*new_selects, distinct=False)
    else:
        new_statement = exp.select(*selects[0])

    if isinstance(statement, exp.Insert):
        insert_expr = exp.insert(
            expression=new_statement,
            columns=statement.this.expressions,
            into=child_table,
            returning=statement.args["returning"],
        )
        insert_expr.set("conflict", statement.args["conflict"])
        statement.replace(insert_expr)
        statement = insert_expr
    elif isinstance(statement, exp.Create):
        expression.pop()
        statement.set("expression", new_statement)
    elif isinstance(statement, exp.CTE):
        expression.pop()
        statement.set("this", new_statement)
    else:
        raise exception.SqlLeafException(message=f"Unknown statement type: {statement.__class__}")

    return statement


@_validate_syntax
def _convert_outer_values_to_select(
    expression: exp.Values, statement: exp.Insert | exp.Create, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.Insert | exp.Create | exp.CTE:
    """
    Transform the query:
        INSERT INTO x (name) VALUES (a), (b)
    into:
        INSERT INTO x (name) SELECT a UNION ALL SELECT b
    so that the lineage functions can process it using build_scope().
    """
    if not isinstance(expression, exp.Values):
        return statement

    columns = [e.name for e in statement.this.expressions]

    return _values_to_select_union(columns, expression, statement=statement, query=query, object_mapping=object_mapping)


def _replace_default_with_value(
    expression: exp.Expr,
    column_name: str,
    table_columns: t.List[exp.ColumnDef],
    query: Q,
    object_mapping: mappings.ObjectMapping,
) -> None:
    """
    Replace a 'DEFAULT' expression with the column's default value or NULL.
    """
    col_def = [col for col in table_columns if col.name == column_name]
    if col_def:
        col_def = col_def[0]
        if default_expr := col_def.find(exp.DefaultColumnConstraint):
            expression.replace(default_expr.this)
        else:
            expression.replace(exp.Null())


@_validate_syntax
def _convert_insert_defaults_to_values(
    statement: exp.Insert, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.Insert:
    """
    Transform the query:
        INSERT INTO x DEFAULT VALUES
    into:
        INSERT INTO x VALUES (DEFAULT, DEFAULT)
    and then:
        INSERT INTO x VALUES (NULL, 42)
    according to the table's default column values.
    """
    child_table = query.get_target_as_table()
    is_default_values = statement.args.get("default", False)
    values = statement.expression

    if not (isinstance(values, exp.Values) or is_default_values):
        return statement

    table_query = object_mapping.find_query(kind="table", table=child_table)
    if not table_query:
        return statement

    table_columns = table_query.get_column_defs()

    if is_default_values:
        # Transform 'DEFAULT VALUES' into 'VALUES (DEFAULT,)'
        values = exp.Values(expressions=[exp.Tuple(expressions=[exp.Var(this="DEFAULT") for _ in table_columns])])
        statement.set("expression", values)
        statement.set("default", False)

    if not isinstance(values, exp.Values):
        return statement

    named_columns = [e for e in statement.this.expressions]

    if not named_columns:
        # Use the associated column names from the mapping
        named_columns = list(table_columns)[: len(values.expressions[0].expressions)]

    for value_expr in values.expressions:
        if isinstance(value_expr, exp.Tuple):
            for i, tuple_expr in enumerate(value_expr.expressions):
                if isinstance(tuple_expr, exp.Var) and tuple_expr.name.upper() == "DEFAULT":
                    # Replace 'DEFAULT' with the associated column's default expression
                    _replace_default_with_value(
                        expression=tuple_expr,
                        column_name=named_columns[i].name,
                        table_columns=table_columns,
                        query=query,
                        object_mapping=object_mapping,
                    )
    return statement


@_validate_syntax
def _convert_update_defaults_to_values(
    statement: exp.Update, query: Q, object_mapping: mappings.ObjectMapping
) -> exp.Update:
    """
    Transform the query:
        UPDATE x SET a = DEFAULT
    into:
        UPDATE x SET a = 42
    according to the table's default column values.
    """
    child_table = query.get_target_as_table()
    table_query = object_mapping.find_query(kind="table", table=child_table)
    if not table_query:
        return statement

    table_columns = table_query.get_column_defs()

    for expr in statement.expressions:
        if isinstance(expr, exp.EQ) and isinstance(expr.left, exp.Column):
            if (isinstance(expr.right, exp.Var) and expr.right.name.upper() == "DEFAULT") or (
                isinstance(expr.right, exp.Column) and expr.right.name.upper() == "DEFAULT"
            ):
                # Replace 'DEFAULT' with the associated column's default expression
                _replace_default_with_value(
                    expression=expr.right,
                    column_name=expr.left.name,
                    table_columns=table_columns,
                    query=query,
                    object_mapping=object_mapping,
                )

    return statement


@_validate_syntax
def _convert_update_to_insert(statement: exp.Update, query: Q, object_mapping: mappings.ObjectMapping) -> exp.Insert:
    """
    Taken from extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

    This transforms an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.
    """
    _UPDATE_FROM_TABLE_ARGS_TO_MOVE = {"joins", "laterals", "pivot"}
    _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT: t.Set[str] = set(exp.Update.arg_types.keys()) - set(
        exp.Select.arg_types.keys()
    )

    if where := statement.args.get("where", None):
        # WHERE statements aren't relevant to lineage
        where.pop()

    # The "SET" expressions need to be converted.
    # For the update command, it'll be a list of EQ expressions, but the select
    # should contain aliased columns.
    alias_names = []
    new_expressions = []
    for expr in statement.expressions:
        if isinstance(expr, exp.EQ):
            if isinstance(expr.left, exp.Tuple):
                # UPDATE x SET (a,b) = (1,2)
                column_names = expr.left.expressions
                column_values = expr.right.expressions
            elif isinstance(expr.left, exp.Column):
                # UPDATE x SET a = 1
                column_names = [expr.left]
                column_values = [expr.right]

            new_columns = zip(column_names, column_values)
            for name_expr, value_expr in new_columns:
                alias_names.append(name_expr.this)
                new_expressions.append(
                    exp.Alias(
                        this=value_expr,
                        alias=name_expr.this,
                    )
                )
        else:
            # If we don't know how to convert it, just leave it as-is. If this causes issues,
            # they'll get caught later.
            new_expressions.append(expr)

    # Special translation for the `from` clause.
    extra_args: dict = {}
    from_table = statement.args.get("from_")
    if from_table and isinstance(from_table, exp.Table):
        from_table = from_table.this
        # Move joins, laterals, and pivots from the Update->From->Table->field
        # to the top-level Select->field.

        for k in _UPDATE_FROM_TABLE_ARGS_TO_MOVE:
            if k in from_table.args:
                # Mutate the from table clause in-place.
                extra_args[k] = from_table.args.get(k)
                from_table.set(k, None)

    # We need to add the CTEs to the insert, not as part of the select.
    # Otherwise the query will be ordered incorrectly (i.e. INSERT .. WITH () .. SELECT)
    with_ = statement.args.get("with_", None)
    if with_:
        with_.pop()

    select_statement = exp.Select(**{
        **{k: v for k, v in statement.args.items() if k not in _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT},
        **extra_args,
        "expressions": new_expressions,
    })

    into_table = util.get_table(statement)
    if not from_table:
        # If the table is a self-reference
        select_statement = select_statement.from_(into_table)

    # Convert the statement into an insert
    insert_expr = exp.insert(
        expression=select_statement,
        columns=alias_names,
        into=into_table,
        returning=statement.args.get("returning", None),
        dialect=query.dialect,
    )
    if with_:
        insert_expr.set("with_", with_)

    statement.replace(insert_expr)
    return insert_expr


@_validate_syntax
def _convert_on_conflict_to_update(
    statement: exp.OnConflict | exp.Update, query: UpdateQuery, object_mapping: mappings.ObjectMapping
) -> exp.Update:
    """
    Convert the 'DO UPDATE' in:
        INSERT INTO <table> as t
        ON CONFLICT
        DO UPDATE SET name = EXCLUDED.name
    to:
        UPDATE <table> AS t
        SET name = name
    so that the expression has the correct columns/values.
    """
    if not isinstance(statement, exp.OnConflict):
        return statement

    parent_insert_expr = None
    if statement.parent and isinstance(statement.parent, (exp.Insert, exp.Create)) and statement.parent.expression:
        if isinstance(statement.parent.expression, exp.Values):
            converted = _convert_outer_values_to_select(
                expression=statement.parent.expression,
                statement=statement.parent,
                query=query,
                object_mapping=object_mapping,
            )
            if isinstance(converted, (exp.Insert, exp.Create)):
                parent_insert_expr = converted
                statement = parent_insert_expr.args["conflict"]
        elif isinstance(statement.parent.expression, exp.Select):
            parent_insert_expr = statement.parent

    update_expr = exp.update(table=query.get_target_as_table())
    update_expr.set("expressions", statement.expressions)

    parent_table = None
    if statement.parent and isinstance(statement.parent, (exp.Insert, exp.Create)) and statement.parent.expression:
        parent_table = statement.parent.expression.args.get("from_", None)
        if parent_table:
            update_expr = update_expr.from_(parent_table.this)

    for eq_expr in list(update_expr.expressions):
        for col in eq_expr.right.find_all(exp.Column):
            if col.table.upper() == "EXCLUDED":
                if parent_insert_expr is None or col.name not in parent_insert_expr.named_selects:
                    # Use the column's default (Postgres)
                    eq_expr.pop()
                else:
                    # Set it to the unaliased expression
                    select_expr = [
                        alias_expr for alias_expr in parent_insert_expr.selects if alias_expr.alias == col.name
                    ][0]
                    new_expr = select_expr.unalias().copy()

                    if isinstance(new_expr, exp.Column) and parent_table:
                        new_expr.set("table", exp.to_identifier(parent_table.alias_or_name))

                    col.replace(new_expr)

    return update_expr


@_validate_syntax
def _add_information_from_merge(
    statement: exp.Insert | exp.Update, query: InsertQuery | UpdateQuery, object_mapping: mappings.ObjectMapping
) -> exp.Insert | exp.Update:
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
            "as_": cte.this,
        }
        for cte in ctes
    ]

    if isinstance(statement, exp.Update):
        # Add the missing information to the UPDATE statement
        target = query.get_target()
        if isinstance(target, exp.Table):
            query.only = target.args.get("only", False)  # type: ignore

        update_expr = statement.table(query.get_target()).from_(using).where(on)
        update_expr.set("returning", returning)

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
            into=query.get_target(),  # ty: ignore[invalid-argument-type]
            dialect=query.dialect,
            returning=returning,
        )

        for cte in new_ctes:
            insert_expr = insert_expr.with_(alias=cte["alias"], as_=cte["as_"])

        statement.replace(insert_expr)
        return insert_expr

    return statement


@_validate_syntax
def _convert_copy_to_insert(
    statement: exp.Copy,
    query: CopyQuery,
    object_mapping: mappings.ObjectMapping,
) -> exp.Insert:
    """
    Convert the COPY statement into an INSERT statement.

    COPY INTO <table> FROM @stage
        -> INSERT INTO <table> SELECT * FROM @stage
        => is_source_a_stage = True
        => produces lineage: @stage -> N table columns
    COPY INTO @stage FROM <table>
        -> INSERT INTO @stage SELECT * FROM <table>
        => is_target_a_stage = True
        => produces lineage: N table columns -> @stage
    """
    dialect = query.dialect

    target_object = query.get_target_object(object_mapping)
    column_names = [col.name for col in target_object.columns]
    columns = [util.column_def_to_column(c.copy()) for c in target_object.columns]
    for c in columns:
        c.set("catalog", "")
        c.set("schema", "")
        c.set("table", "")

    # Transform to a SELECT
    src = query.get_source()
    if isinstance(src, exp.Select):
        select = src
    else:
        select = exp.select(*columns, dialect=dialect).from_(src)

    # Convert the Copy to an Insert
    insert_expr = exp.insert(
        expression=select,
        into=query.get_target(),  # ty: ignore[invalid-argument-type]
        columns=column_names,
        dialect=dialect,
    )
    return insert_expr


@_validate_syntax
def _convert_unload_to_insert(
    statement: exp.Select, query: UnloadQuery, object_mapping: mappings.ObjectMapping
) -> exp.Insert:
    """
    Convert the UNLOAD statement into an INSERT statement.

    UNLOAD ('SELECT * FROM fruit.raw') TO 's3://object-path/name-prefix'
        -> INSERT INTO 's3://object-path/name-prefix' SELECT * FROM fruit.raw
    """
    table = exp.table_(query.get_target().name)
    insert_expr = exp.insert(
        expression=statement,
        into=table,
        dialect=query.dialect,
    )

    return insert_expr


@_validate_syntax
def _validate_values(statement: exp.Insert, query: Q, object_mapping: mappings.ObjectMapping) -> exp.Insert:
    """
    Perform some basic validation of the query. This needs a better place, long-term.
    """
    for expr in statement.walk():
        if isinstance(expr, exp.Values) and isinstance(expr.parent, exp.From):
            if not expr.args["alias"] or not len(expr.args["alias"].columns):
                message = "Expression 'SELECT FROM (VALUES)' currently requires an alias with column names."
                raise exception.SqlLeafException(message=message)

    return statement


EXCLUDE_OPTIMIZER_RULES = [
    "eliminate_ctes",  # Preserve CTEs
    "merge_subqueries",  # Preserve CTEs
    "qualify",  # We qualify when we need to
    "quote_identifiers",  # Preserve identifiers
    "eliminate_subqueries",  # Preserve subqueries
]


def _optimizer_rules(exclude_rules: t.List[str]):
    """
    Return a list of sqlglot.optimizer rules to use.
    """
    return [r for r in RULES if getattr(r, "__name__", None) not in exclude_rules]


@_validate_syntax
def _apply_optimizations(
    statement: E, query: Q, object_mapping: mappings.ObjectMapping, add_column_names: bool = True
) -> E:
    """
    1. We pass infer_schema=True to source unqualified columns from the source table (if missing from `schema` param)
        e.g. so that
            INSERT INTO my.other
            SELECT name
            FROM my.table
        produces
            my.table.name -> my.other.name
    """
    validate_columns = True
    exclude_rules = EXCLUDE_OPTIMIZER_RULES[:]

    # Do not validate the columns if the source is a non-table
    if isinstance(query, CopyQuery):
        src, src_name = query.get_source(), query.get_source().name
        if query.dialect == "postgres":
            if isinstance(src, exp.Identifier) and src_name in ["stdin", "stdout"]:
                validate_columns = False
            elif isinstance(src, exp.Literal):
                validate_columns = False
        elif query.dialect == "snowflake":
            if query.is_source_a_stage:
                validate_columns = False

    if not validate_columns:
        # Prevent overwriting known types to 'UNKNOWN' (sqlglot can't resolve non-table sources)
        exclude_rules += ["annotate_types"]

    qualify.qualify(
        statement,
        schema=object_mapping,
        infer_schema=True,
        dialect=query.dialect,
        isolate_tables=False,
        validate_qualify_columns=validate_columns,
        quote_identifiers=False,
    )
    _add_aliases_to_pseudocolumns(statement=statement, query=query, object_mapping=object_mapping)

    if add_column_names and isinstance(statement, exp.Insert):
        _add_column_names_to_insert(statement=statement, query=query, object_mapping=object_mapping)

    # Selectively apply sqlglot's optimization rules.
    statement = optimize(
        expression=statement, dialect=query.dialect, schema=object_mapping, rules=_optimizer_rules(exclude_rules)
    )

    # We don't want to merge the CTEs as they provide useful info to the user
    # so we skip merge_ctes() and call the function below directly instead
    statement = merge_derived_tables(statement)
    return statement


@_validate_syntax
def _rename_returning_columns(
    statement: exp.CTE, query: Q, object_mapping: mappings.ObjectMapping, child_table: exp.Table
) -> exp.CTE:
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
    returning_expr: exp.Returning = statement.this.args.get("returning", None)
    if not returning_expr:
        return statement

    for col_expr in returning_expr.expressions:
        if not isinstance(col_expr, (exp.Alias, exp.Column, exp.Star)):
            message = f"Non-column expression ({col_expr}) must have an alias inside RETURNING to prevent ambiguity."
            raise exception.SqlLeafException(message=message)

    # Replace the OLD & NEW aliases with the table alias if it exists. Otherwise, remove it to be valid.
    returning_columns = list(returning_expr.find_all(exp.Column))
    for col in returning_columns:
        if col.table.lower() in ["old", "new"]:
            if child_table.alias:
                col.set("table", exp.to_identifier(child_table.alias, quoted=False))
            else:
                col.args["table"].pop()
                if isinstance(col.this, exp.Star):
                    # optimize() needs Star(), not Column(Star())
                    col.replace(col.this)

    if isinstance(statement.this, exp.Merge):
        using = statement.this.args["using"]
        on = statement.this.args["on"]
        new_select = exp.select(*returning_expr.expressions).from_(child_table).join(using, on=on)
    else:
        new_select = exp.select(*returning_expr.expressions).from_(child_table)

    new_select = _apply_optimizations(
        statement=new_select, query=query, object_mapping=object_mapping, add_column_names=False
    )

    statement.set("this", new_select)
    return statement


@_validate_syntax
def _add_column_names_to_insert(statement: exp.Insert, query: Q, object_mapping: mappings.ObjectMapping):
    """
    Add aliases to SELECTs that are missing them by looking at the corresponding INSERT column.
    This prevents sqlglot from assigning its own generated names as aliases.
    This needs to run after qualify() as it expands stars and aliases.

    For example, given table:
        CREATE TABLE my.apple (a VARCHAR, b VARCHAR);
    the statement:
        INSERT INTO my.apple SELECT name, age FROM my.pear
    renames to:
        INSERT INTO my.apple (a,b) SELECT name as a, age as b FROM my.pear
    """
    if not isinstance(statement, exp.Insert) or not statement.selects:
        return

    # sqlglot throws a parse error on named columns for Snowflake: INSERT INTO @"my_eXt_sTaGe" (NAME, AGE) SELECT ...
    if (
        query.dialect == "snowflake"
        and isinstance(query, CopyQuery)
        and (query.is_source_a_stage or query.is_target_a_stage)
    ):
        return

    if isinstance(query, (CopyQuery, UnloadQuery)):
        # The aliases and column names aleady exist from a previous transformation
        return

    child_table = query.get_target_as_table()
    selects = statement.selects
    table_query = object_mapping.get_table_or_stage(child_table)
    if not table_query:
        return
    table_columns = [c.name for c in table_query.get_column_defs(include_system=True)]
    insert_columns = []

    if isinstance(statement.this, exp.Schema):
        # INSERT INTO fruit.raw (name)
        insert_columns = [s.name for s in statement.this.expressions]
    elif isinstance(statement.this, exp.Table):
        # INSERT INTO fruit.raw AS r (name)
        insert_columns = [s for s in statement.this.alias_column_names]

    if not insert_columns:
        # Add the column names from the mapping to the query
        insert_columns = list(table_columns)[: len(selects)]
        schema = exp.Schema(this=child_table, expressions=[exp.to_identifier(c) for c in insert_columns])
        statement.set("this", schema)

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


# def clean_stored_procedure_text(text: str) -> str:
#     """
#     Extract the queries from inside a stored procedure by removing any
#     syntax/keywords that cannot be parsed by sqlglot.
#
#     Parameters:
#         text: text containing a stored procedure
#     """
#     logger.debug("Cleaning stored procedure text.")
#     lines = text.splitlines()
#
#     # Transform the procedure's text
#     lines = remove_lines_before_begin(lines)
#     lines = remove_lines_after_unsupported_syntax(lines)
#     lines = remove_raise_statements(lines)
#
#     return "\n".join(lines)
#
#
# def remove_lines_before_begin(lines: t.List[str], comment=False) -> t.List[str]:
#     """
#     Remove every line until 'BEGIN', inclusive.
#
#     Parameters:
#         lines: list of strings representing a stored procedure
#         comment: whether to comment out the matching lines instead of removing them
#     """
#     stripped_lines = [line.lower().strip() for line in lines]
#
#     # Only process procedures that contain 'begin'
#     if "begin" not in stripped_lines:
#         return lines
#
#     new_lines = copy.copy(lines)
#
#     # Comment out every line until we reach 'begin'
#     for i, line in enumerate(lines):
#         text = line.lower().strip()
#         if not text.startswith("--"):
#             if comment:
#                 line = "-- " + line
#             else:
#                 line = ""
#
#         # Only overwrite/strip new lines
#         new_lines[i] = line
#         if text == "begin":
#             break
#
#     return new_lines
#
#
# def remove_lines_after_unsupported_syntax(lines: t.List[str]) -> t.List[str]:
#     """
#     Remove every line on and after unsupported syntax (e.g. 'EXCEPTION', 'RETURN').
#
#     Parameters:
#         lines: list of strings representing a stored procedure
#     """
#     new_lines = []
#
#     for i, line in enumerate(lines):
#         if line.lower().strip().startswith(("exception", "return ")):
#             break
#         new_lines.append(line)
#
#     return new_lines
#
#
# def remove_raise_statements(lines: t.List[str]) -> t.List[str]:
#     """
#     Remove every line starting with 'RAISE'.
#
#     Parameters:
#         lines: list of strings representing a stored procedure
#     """
#     new_lines = []
#
#     for i, line in enumerate(lines):
#         if line.lower().strip().startswith("raise "):
#             continue
#         new_lines.append(line)
#
#     return new_lines
