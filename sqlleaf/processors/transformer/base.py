import functools
import logging
import typing as t

import sqlglot
from sqlglot import exp
from sqlglot.optimizer import RULES, optimize, qualify
from sqlglot.optimizer.merge_subqueries import merge_derived_tables

from sqlleaf import exception, util
from sqlleaf.models.query import Q, TableQuery
from sqlleaf.processors.transformer import udf
from sqlleaf.processors.transformer.expressions import simplify_row
from sqlleaf.typing import E, SqlObjectType

logger = logging.getLogger("sqlleaf")


EXCLUDE_OPTIMIZER_RULES = [
    "eliminate_ctes",  # Preserve CTEs
    "merge_subqueries",  # Preserve CTEs
    "qualify",  # We qualify when we need to
    "quote_identifiers",  # Preserve identifiers
    "eliminate_subqueries",  # Preserve subqueries
]
LOG_TRANSFORMATIONS = True


class BaseQueryTransformer:
    """
    Base class holding shared transformation helpers.
    Subclasses call these helpers from their transform() method.
    """

    def __init__(self, statement: E, query: Q) -> None:
        self.statement = statement
        self.query = query

    def transform(self, statement: E) -> E:
        """
        Default transformation function that subclasses override to add query-type-specific logic.
        """
        return statement

    def preprocess(self, statement: E) -> E:
        """
        Run a set of transformations over every statement
        BEFORE the type-specific transformations.
        """
        statement = self._expand_to_query(statement)
        statement = self._convert_table_to_select(statement)

        # Remove any FILTER clauses (not used for lineage)
        for filter_expr in statement.find_all(exp.Filter):
            filter_expr.replace(filter_expr.this)

        # Remove WHERE clauses (not used for lineage)
        for where_expr in statement.find_all(exp.Where):
            where_expr.pop()

        simplify_row(statement, self.query)
        return statement

    def postprocess(self, statement: E) -> E:
        """
        Run a set of transformations over every statement
        AFTER the type-specific transformations.
        """
        statement = self._apply_udf_substitutions(statement)
        statement = self._add_aliases_to_udfs(statement)
        statement = self._apply_optimizations(statement)
        return statement

    def _expand_to_query(self, statement: E) -> E:
        """
        Expand Snowflake TABLE(TO_QUERY(SQL => '...')) into an inline subquery.

        Transforms:
            SELECT * FROM TABLE(TO_QUERY(SQL => 'SELECT * FROM source'))
        Into:
            SELECT * FROM (SELECT * FROM source)
        """
        if self.query.dialect == "snowflake":
            for table_from_rows in statement.find_all(exp.TableFromRows):
                anon = table_from_rows.this
                if not (isinstance(anon, exp.Anonymous) and anon.name.upper() == "TO_QUERY"):
                    continue

                # Extract the SQL string - named arg (SQL => '...') or positional first arg
                sql_str = None
                for arg in anon.expressions:
                    if isinstance(arg, exp.Kwarg) and arg.this.name.upper() == "SQL":
                        sql_str = arg.expression.this  # Literal.this gives the string value
                        break
                    if isinstance(arg, exp.Literal) and arg.is_string:
                        sql_str = arg.this
                        break

                if sql_str is None:
                    continue

                # Parse the extracted SQL string
                inner_query = sqlglot.parse_one(sql_str, dialect=self.query.dialect)

                # Wrap as subquery and replace the TableFromRows
                subquery = inner_query.subquery()
                table_from_rows.replace(subquery)

        return statement

    def _apply_udf_substitutions(self, statement: E) -> E:
        """
        Replaces UDF call sites in the transformed statement with their inlined body.
        Must run before _add_aliases_to_udfs so raw exp.Anonymous nodes are still present.

        Example:
            Given a UDF defined as:
                CREATE FUNCTION hello() RETURNS TEXT LANGUAGE SQL RETURN 'Hello';

            And an INSERT statement:
                INSERT INTO target (name) SELECT hello();

            The call site `hello()` is replaced with the inlined UDF body, producing:
                INSERT INTO target (name) SELECT (SELECT 'Hello' AS Hello) AS name
        """
        while True:
            annotated = statement
            node, matched_udf = udf.find_next_udf_call(annotated, self.query.object_mapping)
            if not node:
                break

            target_node = udf.get_target_node(node)
            replacement_exprs = udf.build_replacement_exprs(node, matched_udf)
            if not replacement_exprs:
                break

            if len(replacement_exprs) > 1:
                # Multi-statement UDF body: branch the entire query for each expression,
                # then recursively process each branch to handle remaining UDF calls.
                node_index = next((i for i, n in enumerate(annotated.walk()) if n is target_node), -1)
                if node_index == -1:
                    break
                final_results = []
                for repl_expr in replacement_exprs:
                    new_statement = annotated.copy()
                    for i, n in enumerate(new_statement.walk()):
                        if i == node_index:
                            udf.apply_replacement(n, repl_expr, matched_udf)
                            break
                    # Recursively substitute any remaining UDF calls in this branch
                    substituted = self._apply_udf_substitutions(new_statement)
                    final_results.append(substituted)

                # Return the last statement as the primary statement; for scalar UDFs the last
                # statement is the return value. Others are discarded.
                if final_results:
                    return final_results[-1]
                break
            udf.apply_replacement(target_node, replacement_exprs[0], matched_udf)
        return statement

    def _validate_syntax(func):
        """
        Ensure that the transformed query is parseable.
        """

        @functools.wraps(func)
        def wrapper(self, *args, **kwargs) -> E:
            statement = args[0] if args else kwargs.get("statement", self.statement)
            query = self.query

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
                if query.dialect in ["athena", "redshift"] and isinstance(query, TableQuery) and query.property == "external":
                    # Bug in sqlglot: parsing the output for CREATE EXTERNAL TABLE WITH (FORMAT=TEXTFILE) breaks the parser
                    pass

            return result

        return wrapper

    def _convert_table_to_select(self, statement: E) -> E:
        """
        Convert the statement "TABLE x" to "SELECT * FROM x"
        """
        if self.query.dialect in ["mysql", "postgres"]:
            source = statement.args.get("source", None)
            if source:
                table = source.pop()
                statement.set("expression", exp.select("*").from_(table))
        return statement

    def _add_aliases_to_udfs(self, statement: E) -> E:
        """
        Iterate over the query looking for UDFs and add an alias to them with the same name
        as the UDF if it doesn't already exist. This prevents sqlglot from adding its own
        custom aliases (_0, _1, etc).
        """
        query = self.query
        for node in statement.find_all(exp.Anonymous):
            udf_query = udf.lookup_udf_call(node, query.object_mapping)
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

    def _add_aliases_to_pseudocolumns(self, statement: E) -> E:
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
        if not isinstance(expression, exp.Values):
            return statement

        # Resolved the column names
        if isinstance(statement, exp.CTE):
            columns = statement.alias_column_names
            if not columns:
                columns = [e.name for e in statement.root().this.expressions]
        elif not isinstance(statement, exp.Values):
            columns = [e.name for e in statement.this.expressions]
        else:
            columns = []

        # Fallback: look up from object mapping
        query = self.query
        values_lists: t.List[exp.Tuple] = expression.expressions
        child_table = None

        if not columns:
            try:
                child_table = query.get_target_as_table()
                cols = query.object_mapping.find_columns_for_table(child_table)
                columns = list(cols)[: len(values_lists[0].expressions)]
            except exception.SqlLeafException:
                pass

        if not child_table:
            try:
                child_table = query.get_target_as_table()
            except exception.SqlLeafException:
                pass

        # Build the 'SELECT ... UNION ALL SELECT ...'
        new_statement = util.convert_values_to_select(
            expression=expression,
            dialect=query.dialect,
            column_names=columns,
        )

        # Rewrite the parent statement
        if isinstance(statement, exp.Insert):
            insert_expr = exp.insert(
                expression=new_statement,
                columns=statement.this.expressions,
                into=child_table or statement.this,
                returning=statement.args.get("returning"),
            )
            insert_expr.set("conflict", statement.args.get("conflict"))
            statement.replace(insert_expr)
            statement = insert_expr
        elif isinstance(statement, exp.Create):
            expression.pop()
            statement.set("expression", new_statement)
        elif isinstance(statement, exp.CTE):
            expression.pop()
            statement.set("this", new_statement)
        elif isinstance(statement, exp.Values):
            statement = new_statement
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

    @_validate_syntax
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
        query = self.query
        validate_columns = True
        exclude_rules = EXCLUDE_OPTIMIZER_RULES[:]

        # Do not validate the columns if the source is a non-table
        if not query.source_info or SqlObjectType.type_has_no_column_defs(query.source_info.type):
            validate_columns = False

        # Do not validate columns for SELECT statements with no FROM clause (e.g. UDF body inner queries
        # that have table-qualified columns from parameter substitution but no actual FROM tables).
        # For example, after substitution of 'MY_UDF(people.*)' with 'MY_UDF = SELECT $1.age AS age'
        if isinstance(statement, exp.Select) and not statement.args.get("from"):
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
            expression=statement,
            dialect=query.dialect,
            schema=query.object_mapping,
            rules=self._optimizer_rules(exclude_rules),
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
        returning_expr: exp.Returning = statement.this.args.get("returning", None)
        if not returning_expr:
            return statement

        for col_expr in returning_expr.expressions:
            if not isinstance(col_expr, (exp.Alias, exp.Column, exp.Star)):
                message = (
                    f"Non-column expression ({col_expr}) must have an alias inside RETURNING to prevent ambiguity."
                )
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
            "using": merge_expr.args["using"],
            "on": merge_expr.args["on"],
            "returning": merge_expr.args.get("returning"),
            "ctes": ctes,
        }

    @staticmethod
    def _extract_multitable_insert_context(statement: exp.Insert) -> dict | None:
        """
        Extract the shared source from the parent MultitableInserts statement.
        """
        multitable_insert = statement.find_ancestor(exp.MultitableInserts)
        if not multitable_insert:
            return None

        source = multitable_insert.args.get("source")
        return {
            "source": source,
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
        query = self.query
        if not isinstance(statement, exp.Insert) or not statement.selects:
            return statement

        # sqlglot throws a parse error on named columns for Snowflake: INSERT INTO @"my_eXt_sTaGe" (NAME, AGE) SELECT ...
        SKIP_COLUMN_RENAME_TYPES = SqlObjectType.type_has_no_column_defs(query.source_info.type, query.target_info.type)
        if SKIP_COLUMN_RENAME_TYPES:
            # The aliases and column names already exist from a previous transformation,
            # or the target is not a table (e.g. S3 file, stage, stream)
            return statement

        child_table = query.get_target_as_table()
        table_query = query.object_mapping.get_table_or_stage(child_table)
        if not table_query:
            raise exception.SqlLeafException(message=f"Unknown target table: {str(exp.table_name(child_table))}")

        table_columns = [c.name for c in table_query.get_column_defs(include_system=True)]
        selects = statement.selects
        insert_columns = self._extract_insert_columns(statement, child_table, include_system=True)

        # Add the column names from the mapping to the INSERT's column names
        insert_columns = list(insert_columns)[: len(selects)]
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
            raise exception.SqlLeafException(message=message, table=child_table)

        aliases = util.get_selected_column_names(statement)
        if aliases != insert_columns:
            message = "Mismatched column names: column names (%s) do not match column aliases (%s)" % (
                ",".join(insert_columns),
                ",".join(aliases),
            )
            # logger.warning(message)

        for i, ins in enumerate(insert_columns):
            # Overwrite the aliases because sqlglot may have added incorrect ones
            statement.selects[i] = statement.selects[i].as_(ins)

        return statement

    def _extract_insert_columns(
        self, statement: exp.Insert, target: exp.Table | exp.Schema, include_system: bool = False
    ) -> t.List[str]:
        """
        Returns a list of column names for an exp.Insert statement.
        """
        if isinstance(statement.this, exp.Schema):
            return [s.name for s in statement.this.expressions]

        columns = []
        if isinstance(statement.this, exp.Table):
            columns = statement.this.alias_column_names
        elif isinstance(statement.this, exp.Tuple):
            columns = [s.alias_or_name for s in statement.this.expressions]

        if columns:
            return columns

        # Fall back to the table's definition in the mapping
        table_query = self.query.object_mapping.get_table_or_stage(target)
        if not table_query:
            return []

        return [c.name for c in table_query.get_column_defs(include_system=include_system)]

    @staticmethod
    def _extract_value_lists(expression: exp.Expression) -> t.List[t.List[exp.Expression]]:
        """
        Promoted from InsertTransformer._get_insert_values.
        Handles exp.Values, exp.Tuple, exp.Select, and exp.Union.
        """
        values_lists = []
        if isinstance(expression, exp.Values):
            values_lists = [t.expressions for t in expression.expressions]
        elif isinstance(expression, exp.Tuple):
            values_lists = [expression.expressions]
        elif isinstance(expression, exp.Select):
            values_lists = [[s.unalias() for s in expression.expressions]]
        elif isinstance(expression, exp.Union):
            # Already converted to UNION of SELECTs by _convert_values_to_select
            values_lists = [[s.unalias() for s in select.expressions] for select in expression.find_all(exp.Select)]

        return values_lists

    def _convert_update_to_insert(self, statement: exp.Update) -> exp.Insert:
        """
        Taken from extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

        This transforms an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.
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
                if isinstance(expr.left, exp.Paren) and isinstance(expr.right, exp.Subquery):
                    # UPDATE x SET (a) = (SELECT a FROM ...)
                    column_names = [expr.left.this]
                    subquery = expr.right.this  # the inner SELECT
                    column_values = []
                    for col_expr in subquery.expressions:
                        column_values.append(col_expr.unalias())
                    subquery_from = subquery.args.get("from_")
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
