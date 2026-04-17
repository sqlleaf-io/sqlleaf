from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, replace, InitVar

import networkx as nx
from sqlglot import exp

from sqlleaf import util, mappings, sqlglot_lineage, exception

logger = logging.getLogger("sqleaf")

DMLQueryType = t.Union[exp.Insert, exp.Update, exp.Merge, exp.Select]

class Query:
    def __init__(
        self,
        kind: str,
        dialect: str,
        statement: exp.Expression,
        child_table: exp.Table,
        statement_index: int,
        has_statement: bool = True,
    ):
        self.kind = kind
        self.dialect = dialect
        self.statement = statement
        self.child_table = child_table  # The target table
        self.statement_index = statement_index  # The position of this query within a list of queries
        self.parent_query = None
        self.child_queries = []
        self.has_statement = has_statement  # Has a DML statement (Insert, Update, Merge)

        self.statement_original = statement.copy()
        self.statement_transformed = None
        self.set_statement(self.statement_original)

        logger.debug(f"Created Query: {self.__class__}")

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        if self.parent_query:
            index = self.parent_query.get_statement_index()
            return index + ':' + str(self.statement_index)
        else:
            return str(self.statement_index)

    def set_statement(self, statement: exp.Expression):
        self.statement = statement
        text = self.statement.sql()
        self.text_original = text
        self.text_length = len(text)
        self.text_sha256_hash = util.long_sha256_hash(text)

        self.set_id()

    def set_id(self):
        """
        Consider the query's index in the ID as there may be duplicate queries provided
        (e.g. in a stored procedure).
        """
        self.id = "query:" + util.short_sha256_hash(self.text_original + ":" + str(self.statement_index))

    def set_to_original(self):
        """
        Convert the Query back to its original statement.

        This is needed for CTAS/View queries after they transform into Inserts in order to have their lineage calculated.
        This is the inverse of functions like set_as_insert()
        """
        self.set_statement(statement=self.statement_original)

    def add_child_query(self, child_query):
        child_query.parent_query = self
        self.child_queries.append(child_query)

    def add_child_queries(self, child_queries: t.List):
        for query in child_queries:
            self.add_child_query(query)

    def get_all_queries(self, types: t.Tuple = None):
        """
        Collect all queries (children + self) recursively of a certain type.
        """
        all_queries = []

        for child in self.child_queries:
            all_queries.append(child)
            all_queries.extend(child.get_all_queries())

        if not self.parent_query:
            # We're the root node
            all_queries = [self] + self.child_queries
            all_queries = [q for q in all_queries if types and isinstance(q, types)]

        return all_queries

    def collect_writable_cte_queries(self, expr: DMLQueryType, dialect: str, object_mapping: mappings.ObjectMapping):
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
        for i, cte in enumerate(getattr(expr, 'ctes', [])):
            cte_expr = cte.this

            if isinstance(cte_expr, exp.Merge):
                query = MergeQuery(expr=cte_expr, dialect=dialect, object_mapping=object_mapping, statement_index=i)
            elif isinstance(cte_expr, exp.Insert):
                query = InsertQuery(expr=cte_expr, dialect=dialect, object_mapping=object_mapping, statement_index=i)
            elif isinstance(cte_expr, exp.Update):
                query = UpdateQuery(expr=cte_expr, dialect=dialect, statement_index=i)
            else:
                continue

            # Detach the query in the AST so that certain transformations work later
            query.statement.pop()
            self.add_child_query(query)

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.index,
            "text_original": self.text_original,
            "text_length": self.text_length,
            "text_sha256_hash": self.text_sha256_hash,
            "stored_procedure": {},
        }
        return result


class MergeQuery(Query):
    def __init__(self, expr: exp.Merge, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="merge",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=expr.this,
        )

        self.using = expr.args["using"]
        self.on = expr.args["on"]
        if ret := expr.args["returning"]:
            self.returning = ret.expressions
        else:
            self.returning = []

        if "with_" in expr.args:
            self.ctes = expr.args["with_"].expressions
        else:
            self.ctes = []

        self.whens = []
        self.child_expressions = []
        self.collect_writable_cte_queries(expr, dialect, object_mapping)
        self.collect_and_transform_child_expressions(expr, dialect, object_mapping)

    def collect_and_transform_child_expressions(self, expr: exp.Merge, dialect: str, object_mapping: mappings.ObjectMapping):
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
        # TODO: should this be in transforms.py?
        self.whens = [when.args["then"] for when in expr.args["whens"].expressions]
        merge = self

        for i, when in enumerate(self.whens):
            # Copy the CTEs
            new_ctes = [
                {
                    "alias": cte.alias_or_name,
                    "as_": cte.this.sql(),
                }
                for cte in self.ctes
            ]

            if isinstance(when, exp.Update):
                update_expr = when.table(merge.child_table).from_(merge.using).where(merge.on)

                for cte in new_ctes:
                    update_expr = update_expr.with_(alias=cte["alias"], as_=cte["as_"])

                update_query = UpdateQuery(expr=update_expr, dialect=self.dialect, statement_index=i)
                self.add_child_query(update_query)

            elif isinstance(when, exp.Insert):
                new_columns = when.expression.expressions
                new_aliases = when.this.expressions

                aliases = [exp.alias_(str(col), str(alias)) for col, alias in zip(new_columns, new_aliases)]

                # Build a new SELECT
                new_select = exp.select(*aliases).from_(merge.using)

                # insert
                insert_expr = exp.insert(
                    expression=new_select,
                    columns=[col.this for col in when.this.expressions],
                    into=merge.child_table,
                    dialect=dialect,
                )
                for cte in new_ctes:
                    insert_expr = insert_expr.with_(alias=cte["alias"], as_=cte["as_"])

                insert_query = InsertQuery(expr=insert_expr, dialect=self.dialect, object_mapping=object_mapping, statement_index=i)
                self.add_child_query(insert_query)


class SelectQuery(Query):
    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        child_table = util.get_table(expr)
        super().__init__(
            kind="select",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=child_table,
        )
        self.collect_writable_cte_queries(expr, dialect, object_mapping)


class InsertQuery(Query):
    def __init__(self, expr: exp.Insert, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        child_table = util.get_table(expr)
        super().__init__(
            kind="insert",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=child_table,
        )
        self.convert_values_to_select(object_mapping)
        self.collect_writable_cte_queries(expr, dialect, object_mapping)


    def convert_values_to_select(self, object_mapping: mappings.ObjectMapping):
        """
        Transform an
            INSERT INTO x VALUES (...)
        into an
            INSERT INTO x SELECT ...
        so that the lineage functions can process it.

        We don't attempt to add the column names from the mapping as we may have
        stars in the columns. This comes later.
        """
        if isinstance(self.statement.expression, exp.Values):

            values = self.statement.expression.expressions[0].expressions
            columns = [e.name for e in self.statement.this.expressions]

            if not columns:
                cols = object_mapping.find_columns_for_table(self.child_table)
                columns = list(cols)[:len(values)]

            selects = [exp.alias_(val, str(col)) for col, val in zip(columns, values)]
            new_select = exp.select(*selects)
            insert_expr = exp.insert(
                expression=new_select,
                columns=self.statement.this.expressions,
                into=self.child_table,
            )

            self.set_statement(insert_expr)


class UpdateQuery(Query):
    def __init__(self, expr: exp.Update, dialect: str, statement_index: int):
        super().__init__(
            kind="update",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(expr),
        )
        self.convert_update_to_insert()

    def convert_update_to_insert(self):
        """
        Taken from function extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

        This transforms an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.
        """
        _UPDATE_FROM_TABLE_ARGS_TO_MOVE = {"joins", "laterals", "pivot"}
        _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT: t.Set[str] = set(exp.Update.arg_types.keys()) - set(exp.Select.arg_types.keys())

        statement = self.statement.copy()
        if (where := statement.args.get('where', None)):
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
            into=statement.this
        )
        self.set_statement(insert_statement)


class CTASQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        columns: t.List[exp.ColumnDef],
        statement_index: int,
    ):
        super().__init__(
            kind="ctas",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement),
        )
        self.column_defs = columns

    def get_column_defs(self) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.column_defs}
        return columns


class ViewQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        columns: t.List[exp.ColumnDef],
        statement_index: int,
    ):
        super().__init__(
            kind="view",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement),
        )
        self.column_defs = columns

    def get_column_defs(self) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.column_defs}
        return columns


class TableQuery(Query):
    def __init__(self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="table",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement.this),
            has_statement = False,
        )
        self.column_defs = []

        self.set_column_defs(object_mapping)

    def get_column_defs(self) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def set_column_defs(self, object_mapping: mappings.ObjectMapping):
        """
        Collect all the column definitions for this table.
        """
        statement = self.statement
        columns = list(statement.find_all(exp.ColumnDef))

        # Set the column's 'default' type to the column's own type (it is sometimes missing)
        for col_def in columns:
            if default := col_def.find(exp.DefaultColumnConstraint):
                default.this.type = col_def.kind

        # Process the table's properties: INHERITS, LIKE, etc
        if inherited_props := list(statement.find_all(exp.InheritsProperty)):
            inherited_columns = self.find_inherited_columns(inherited_props, object_mapping)
            columns += inherited_columns

        if like_property := statement.find(exp.LikeProperty):
            like_columns = self.find_like_columns(like_property, object_mapping)
            columns += like_columns

        self.column_defs = columns

    def find_inherited_columns(self, inherits_properties: t.List[exp.InheritsProperty], object_mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b INHERITS (a)'
        """
        columns = []

        for inh_prop in inherits_properties:
            inh_table = inh_prop.find(exp.Table)
            inh_table_query = object_mapping.find_query(kind='table', table=inh_table)
            columns.extend(inh_table_query.column_defs)

        return columns

    def find_like_columns(self, like_property: exp.LikeProperty, object_mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b (LIKE a)'.
        Postgres allows only 1 table to be referenced in LIKE.
        """
        columns = []
        property_names = []

        for like_prop in like_property.expressions:
            # sqlglot concats properties with '='
            property_names.append(str(like_prop).replace('=', ' '))

        properties = self.get_properties_to_include(property_names)

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
                                message = f"Column '{inner_col.name}' does not exist in table '{self.child_table}'."
                                raise exception.SqlLeafException(message=message)

                            inner_col.set('catalog', exp.to_identifier(self.child_table.catalog))
                            inner_col.set('db', exp.to_identifier(self.child_table.db))
                            inner_col.set('table', exp.to_identifier(self.child_table.this))
                            inner_col.type = referenced_parent_col_def.kind
                else:
                    # Discard the column's expression
                    if prop_expr:
                        prop_expr.parent.pop()

            columns.append(new_col)

        return columns

    def get_properties_to_include(self, options: t.List[str]) -> t.Dict:
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

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema

        Returns: {'col1': 'INT', 'col2': 'VARCHAR'}
        """
        columns = {c.name: str(c.kind) for c in self.column_defs}
        return columns


class ProcedureQuery(Query):
    """
    Holds metadata related to stored procedures.
    """

    def __init__(self, statement: exp.Create, dialect: str, statement_index: int):
        table = util.get_table(statement)
        super().__init__(
            kind="procedure",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=table,
        )

        sql = statement.sql()
        self.schema = table.db
        self.procedure = table.name
        self.signature = str(statement.this)  # e.g. etl.my_proc(v_session_id VARCHAR)
        self.text_original = sql  # For tracking/debugging purposes
        self.text_hash = util.long_sha256_hash(sql)
        self.set_id()

        # TODO: support 'default'
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in statement.this.find_all(exp.ColumnDef)
        ]

        self.set_statement(statement)

    def set_id(self):
        self.id = "procedure:" + util.short_sha256_hash(self.text_original)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "signature": self.signature,
            "args": self.args,
            "text_hash": self.text_hash,
            "text": self.text_original,
        }

    @property
    def name(self):
        return ".".join([var for var in [self.schema, self.procedure] if var])


class UserDefinedFunctionQuery(Query):
    def __init__(
        self,
        schema,
        function,
        dialect,
        args,
        return_type,
        return_expr,
        returns_null,
        language,
        statement,
        statement_index: int,
    ):
        super().__init__(
            kind="user_defined_function",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=statement.this.this,
        )
        self.schema = schema
        self.function = function
        self.return_type = return_type
        self.return_expr = return_expr
        self.returns_null = returns_null
        self.language = language
        self.args = args

        # TODO: support 'default'
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in statement.this.find_all(exp.ColumnDef)
        ]

    @property
    def name(self):
        return ".".join([var for var in [self.schema, self.function] if var])


class SequenceQuery(Query):
    def __init__(self, statement: exp.Create, dialect: str, statement_index: int):
        super().__init__(
            kind="sequence",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=statement.this,
            has_statement=False,
        )


class TriggerQuery(Query):
    def __init__(self, statement: exp.Create, dialect: str, statement_index: int):
        """
        Example:
            CREATE TRIGGER before_fruit_insert
                BEFORE INSERT ON fruit.processed
                FOR EACH ROW
                EXECUTE FUNCTION check_fruit('apple');
        """
        properties = statement.args["properties"].expressions[0]
        super().__init__(
            kind="trigger",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=properties.args["table"],
        )
        self.name = statement.name  # before_fruit_insert
        self.table = properties.args["table"]  # Table(fruit.processed)
        self.timing = properties.args["timing"]  # BEFORE
        self.events = properties.args["events"]  # [TriggerEvent(INSERT)]
        self.execute = properties.args["execute"].this  # Anonymous(check_fruit())
        self.execute_args = self.execute.expressions  # [Literal(apple)]


class StageQuery(Query):
    def __init__(self, statement: exp.Create, dialect: str, statement_index: int):
        super().__init__(
            kind="stage",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement),
            has_statement=False,
        )
        # Needed due to a bug in sqlglot. Never access the table name via print()!
        #  as it prints double-double quotes
        stage_name = str(self.child_table.this)
        self.child_table.this.set("this", "@" + stage_name)
        self.child_table.this.set("quoted", False)

    def get_column_defs(self) -> t.List[exp.ColumnDef]:
        return self.column_defs


class CopyQuery(Query):
    def __init__(self, expr: exp.Copy, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="copy",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=expr.this,
        )
        self.source = expr.args['files'][0]
        self.target = expr.args['this']
        self.is_source_a_stage = False
        self.is_target_a_stage = False

        if dialect == 'snowflake':
            self.configure_stage(expr)

        self.set_as_insert(expr, dialect, object_mapping)

    def configure_stage(self, expr: exp.Copy):
        """
        Set the name if we are a Snowflake 'stage'.
        This involves manually normalising (uppercasing) the name.
        sqlglot only normalizes columns - see comments in `sqlglot.optimizer.normalize_identifiers()`
        """
        source = expr.args['files'][0]
        target = expr.args['this']

        if str(source).startswith("@"):
            self.is_source_a_stage = True
            if not str(source).startswith('@"'):
                source.this.set("this", str(source).upper())

        elif str(target).startswith("@"):
            self.is_target_a_stage = True
            if not str(target).startswith('@"'):
                target.this.set("this", str(target).upper())

    def set_as_insert(self, expr, dialect, object_mapping):
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
        if self.is_source_a_stage:
            child_table = expr.this
            parent_table = expr.args['files'][0]
            source_table = child_table
        elif self.is_target_a_stage:
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

        if self.is_target_a_stage:
            # Any object that is referenced as a source table needs to be added to the table mapping
            # for the lineage functions to work - such as this Stage
            col_defs = [exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DataType.build(type)) for name, type in child_columns.items()]

            child_table_query = object_mapping.find_query(kind='stage', table=child_table)
            child_table_query.column_defs = col_defs

        # We don't worry about `self.is_source_a_stage` here as that is handled in the process_column() later

        self.set_statement(expr_insert)


class PutQuery(Query):
    def __init__(self, expr: exp.Put, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="put",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=expr.this,
        )
        self.source = expr.name
        self.target = expr.args['target'].name
