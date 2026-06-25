import functools
import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer import RULES, optimize, qualify
from sqlglot.optimizer.merge_subqueries import merge_derived_tables

from sqlleaf import exception, util
from sqlleaf.models.query import Q
from sqlleaf.processors.transformers import resolver
from sqlleaf.typing import E
# from sqlleaf.processors.transformers.row import _simplify_row_composite_access

logger = logging.getLogger("sqlleaf")


EXCLUDE_OPTIMIZER_RULES = [
    "eliminate_ctes",  # Preserve CTEs
    "merge_subqueries",  # Preserve CTEs
    "qualify",  # We qualify when we need to
    "quote_identifiers",  # Preserve identifiers
    "eliminate_subqueries",  # Preserve subqueries
]


class BaseQueryTransformer:
    """
    Base class holding shared transformation helpers.
    Subclasses call these helpers from their transform() method.
    """

    def __init__(self, statement: E, query: Q) -> None:
        self.statement = statement
        self.query = query

    def transform(self) -> exp.Expr:
        """
        Default transform for pass-through query types (e.g. TableQuery).
        Subclasses override this to add query-type-specific logic.
        Post-processing (_add_aliases_to_udfs + _apply_optimizations) is applied
        by the caller via _postprocess().
        """
        return self.statement

    def _postprocess(self, stmt: exp.Expr) -> exp.Expr:
        """
        Universal post-processing applied after every type-specific transform.
        Updates self.statement, runs _add_aliases_to_udfs, then _apply_optimizations.
        """
        self.statement = stmt
        self._add_aliases_to_udfs()
        return self._apply_optimizations(stmt)

    def _preprocess(self) -> None:
        """
        Universal pre-processing applied to every statement before type-specific transform.
        - Runs _convert_table_to_select.
        - Removes FILTER and WHERE clauses.
        Updates self.statement in place.
        """
        self.statement = self._convert_table_to_select()
        # Remove any FILTER clauses (aggregate filters not used for lineage)
        for filter_expr in self.statement.find_all(exp.Filter):
            filter_expr.replace(filter_expr.this)
        # Remove WHERE clauses (not used for column-level lineage)
        for where_expr in self.statement.find_all(exp.Where):
            where_expr.pop()
        # _simplify_row_composite_access(self.statement, self.query)

    def _validate_syntax(func):
        """
        Ensure that the transformed query is parseable.
        """
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> E:
            # statement = kwargs.pop("statement")
            # query = kwargs.pop("query")
            statement = self.statement
            query = self.query

            LOG_TRANSFORMATIONS = True

            if LOG_TRANSFORMATIONS:
                logger.debug(f"Function: {func.__name__}, Input:  {statement.sql(dialect=query.dialect)}")

            result = func(self, *args, **kwargs)

            if LOG_TRANSFORMATIONS:
                logger.debug(f"Function: {func.__name__}, Output: {result.sql(dialect=query.dialect)}")

            if result and (statement.sql(dialect=query.dialect) != result.sql(dialect=query.dialect)):
                logger.debug(f"Transformed by {func}.")

            if result is None:
                return result

            try:
                sqlglot.parse_one(result.sql(dialect=query.dialect), dialect=query.dialect)
            except sqlglot.errors.ParseError:
                from sqlleaf.models.query import TableQuery
                if query.dialect == "redshift" and isinstance(query, TableQuery) and query.property == "external":
                    # Bug in sqlglot: parsing the output for CREATE EXTERNAL TABLE WITH (FORMAT=TEXTFILE) breaks the parser
                    pass

            return result

        return wrapper

    def _convert_table_to_select(self) -> E:
        """
        Convert the statement "TABLE x" to "SELECT * FROM x"
        """
        statement = self.statement
        query = self.query
        source = statement.args.get("source", None)
        if source:
            table = source.pop()
            statement.set("expression", exp.select("*").from_(table))
        return statement

    def _add_aliases_to_udfs(self) -> exp.Expr:
        """
        Iterate over the query looking for UDFs and add an alias to them with the same name
        as the UDF if it doesn't already exist. This prevents sqlglot from adding its own
        custom aliases (_0, _1, etc).
        """
        statement = self.statement
        query = self.query
        for node in statement.find_all(exp.Anonymous):
            udf_query = resolver.lookup_udf_call(node, query.object_mapping)
            if not udf_query:
                continue

            # Get the name of the UDF to use as an alias
            name = node.this if isinstance(node.this, str) else node.this.name

            # The expression to be aliased
            to_alias = node
            if isinstance(node.parent, exp.Dot):
                to_alias = node.parent

            # If it's a Table's this (e.g. SELECT * FROM MY_UDF())
            if isinstance(to_alias.parent, exp.Table):
                table_node = to_alias.parent
                if not table_node.alias:
                    table_node.set("alias", exp.TableAlias(this=exp.to_identifier(name)))
                continue

            # If it's in a SELECT list and not already aliased
            if isinstance(to_alias.parent, exp.Select) and to_alias in to_alias.parent.expressions:
                # Wrap the expression in an Alias
                to_alias.replace(exp.alias_(to_alias.copy(), name))

        return statement

    def _add_aliases_to_pseudocolumns(self, statement: exp.Expr | None = None) -> None:
        """
        Given a query:
            SELECT xmax FROM fruit.raw
        rename it to:
            SELECT raw.xmax FROM fruit.raw
        or use the table's alias instead.

        This requires that the tables and columns have run through qualify()
        """
        if statement is None:
            statement = self.statement
        for pseudo in statement.find_all(exp.Pseudocolumn):
            if pseudo.table:
                continue

            if pseudo.parent_select and pseudo.parent_select.args.get("from_"):
                from_table_alias = pseudo.parent_select.args["from_"].alias_or_name
                pseudo.set("table", exp.to_identifier(from_table_alias))

        return statement

    def _process_inner_ctes(self, statement: E) -> E:
        """
        Transform any inner CTE statements.
        """
        if not isinstance(statement, (exp.Insert | exp.Merge | exp.Update | exp.Delete)):
            return statement

        for cte_expr in getattr(statement, "ctes", []):
            if isinstance(cte_expr.this, exp.Update):
                # Replace the inner UPDATE with an INSERT first.
                # The inner query is different from the child query, which is its own separate copy.
                inner_expr = self._convert_update_to_insert(cte_expr.this)
                cte_expr.this.replace(inner_expr)

            elif cte_expr.this.is_star:
                # VALUES() has already been transformed into SELECT * FROM (VALUES())
                from_ = cte_expr.this.args["from_"].this

                if isinstance(from_, exp.Values):
                    values_expr = self._convert_values_to_select(expression=from_, statement=cte_expr)
                    cte_expr.this.replace(values_expr)

            # Rename the columns and replace the INSERT with the SELECT
            self._rename_returning_columns(statement=cte_expr, child_table=cte_expr.find(exp.Table))

        return statement

    def _convert_values_to_select(
        self,
        expression: exp.Values,
        statement: E,
    ) -> E:
        """
        Convert a VALUES(...) clause into a SELECT ... UNION ALL SELECT ... form
        and rewrite the parent statement in-place.
        """
        if not isinstance(statement, (exp.CTE, exp.Insert, exp.Create)):
            return statement

        if not isinstance(expression, exp.Values):
            return statement

        # Resolved the column names
        if isinstance(statement, exp.CTE):
            columns = statement.alias_column_names
            if not columns:
                columns = [e.name for e in statement.root().this.expressions]
        else:
            columns = [e.name for e in statement.this.expressions]

        # Fallback: look up from object mapping
        query = self.query
        values_lists: t.List[exp.Tuple] = expression.expressions
        child_table = query.get_target_as_table()

        if not columns:
            cols = query.object_mapping.find_columns_for_table(child_table)
            columns = list(cols)[: len(values_lists[0].expressions)]

        # Build the 'SELECT ... UNION ALL SELECT ...'
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

        # Rewrite the parent statement
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

    def _replace_default_with_value(
        self,
        expression: exp.Expr,
        column_name: str,
        table_columns: t.List[exp.ColumnDef],
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

    def _optimizer_rules(self, exclude_rules: t.List[str]):
        """
        Return a list of sqlglot.optimizer rules to use.
        """
        return [r for r in RULES if getattr(r, "__name__", None) not in exclude_rules]

    def _apply_optimizations(self, statement: E, add_column_names: bool = True) -> E:
        """
        1. We pass infer_schema=True to source unqualified columns from the source table (if missing from `schema` param)
            e.g. so that
                INSERT INTO my.other
                SELECT name
                FROM my.table
            produces
                my.table.name -> my.other.name
        """
        from sqlleaf.typing import SqlObjectType
        query = self.query
        validate_columns = True
        exclude_rules = EXCLUDE_OPTIMIZER_RULES[:]

        # Do not validate the columns if the source is a non-table
        if query.source_info.type in [SqlObjectType.STREAM, SqlObjectType.FILE, SqlObjectType.STAGE, SqlObjectType.PROGRAM]:
            validate_columns = False

        if not validate_columns:
            # Prevent overwriting known types to 'UNKNOWN' (sqlglot can't resolve non-table sources)
            exclude_rules += ["annotate_types"]

        # TODO: override sqlglot's function that generates table aliases (e.g. _0, _1, etc) into one that handles UDFs (by assigning the alias as the table name)

        qualify.qualify(
            statement,
            schema=query.object_mapping,
            infer_schema=True,
            dialect=query.dialect,
            isolate_tables=False,
            validate_qualify_columns=validate_columns,
            quote_identifiers=False,
        )

        self._add_aliases_to_pseudocolumns(statement)

        if add_column_names and isinstance(statement, exp.Insert):
            self._add_column_names_to_insert(statement)

        # Selectively apply sqlglot's optimization rules.
        statement = optimize(
            expression=statement, dialect=query.dialect, schema=query.object_mapping, rules=self._optimizer_rules(exclude_rules)
        )

        # We don't want to merge the CTEs as they provide useful info to the user
        # so we skip merge_ctes() and call its sibling function below directly instead
        statement = merge_derived_tables(statement)
        return statement

    def _rename_returning_columns(self, statement: exp.CTE, child_table: exp.Table) -> exp.CTE:
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
        query = self.query
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

        new_select = self._apply_optimizations(new_select, add_column_names=False)

        statement.set("this", new_select)
        return statement

    @staticmethod
    def _extract_merge_context(statement: exp.Insert | exp.Update) -> dict | None:
        """
        Extract the shared preamble needed by both INSERT and UPDATE branches of
        _add_information_from_merge.  Returns None if the statement is not nested
        inside a MERGE expression.
        """
        merge_expr = statement.find_ancestor(exp.Merge)
        if not merge_expr:
            return None

        ctes = merge_expr.args["with_"].expressions if "with_" in merge_expr.args else []
        return {
            "merge_expr": merge_expr,
            "using":      merge_expr.args["using"],
            "on":         merge_expr.args["on"],
            "returning":  merge_expr.args.get("returning"),
            "ctes":       ctes,
        }


    def _add_column_names_to_insert(self, statement: exp.Insert) -> exp.Insert:
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
        from sqlleaf.typing import SqlObjectType
        query = self.query
        if not isinstance(statement, exp.Insert) or not statement.selects:
            return statement

        # sqlglot throws a parse error on named columns for Snowflake: INSERT INTO @"my_eXt_sTaGe" (NAME, AGE) SELECT ...
        SKIP_COLUMN_RENAME_TYPES = {SqlObjectType.STREAM, SqlObjectType.FILE, SqlObjectType.STAGE, SqlObjectType.PROGRAM}
        if query.source_info.type in SKIP_COLUMN_RENAME_TYPES or query.target_info.type in SKIP_COLUMN_RENAME_TYPES:
            # The aliases and column names already exist from a previous transformation,
            # or the target is not a table (e.g. S3 file, stage, stream)
            return statement

        # TODO: get the column definitions from the underlying query.TargetObject?
        child_table = query.get_target_as_table()
        selects = statement.selects
        table_query = query.object_mapping.get_table_or_stage(child_table)
        if not table_query:
            raise exception.SqlLeafException(message=f"Unknown target table: {str(exp.table_name(child_table))}")

        table_columns = [c.name for c in table_query.get_column_defs(include_system=True)]
        insert_columns = []

        if isinstance(statement.this, exp.Schema):
            # INSERT INTO fruit.raw (name)
            insert_columns = [s.name for s in statement.this.expressions]
        elif isinstance(statement.this, exp.Table):
            # INSERT INTO fruit.raw AS r (name)
            insert_columns = [s for s in statement.this.alias_column_names]

        if not insert_columns:
            # Add the column names from the mapping to the INSERT's column names
            insert_columns = list(table_columns)[: len(selects)]
            schema = exp.Schema(this=child_table, expressions=[exp.to_identifier(c) for c in insert_columns])
            statement.set("this", schema)

        unknown_columns = [col for col in insert_columns if col not in table_columns]
        if unknown_columns:
            raise exception.SqlLeafException(
                message=f"Unknown columns used in SELECT: {list(unknown_columns)}",
                table=str(exp.table_name(child_table)),
            )

        if exp.Star() in selects:
            raise exception.SqlLeafException(
                message=f"Statement has unresolved star column: {statement.sql(dialect=query.dialect)}",
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

        return statement

    def _convert_update_to_insert(self, statement: exp.Update) -> exp.Insert:
        """
        Taken from extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

        This transformers an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.
        Subclasses (UpdateTransformer) may override this with a more specific implementation.
        """
        query = self.query
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
        subquery_from = None
        for expr in statement.expressions:
            if isinstance(expr, exp.EQ):
                if isinstance(expr.left, exp.Tuple) and isinstance(expr.right, exp.Subquery):
                    # UPDATE x SET (a,b) = (SELECT a, b FROM ...)
                    column_names = expr.left.expressions
                    subquery = expr.right.this  # the inner SELECT
                    column_values = []
                    for col_expr in subquery.expressions:
                        column_values.append(col_expr.unalias())
                    subquery_from = subquery.args.get("from_")

                elif isinstance(expr.left, exp.Tuple):
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
        if subquery_from:
            # If the SET used a subquery, use its FROM clause
            select_statement = select_statement.from_(subquery_from.this)
        elif not from_table:
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
