from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, replace, InitVar

import networkx as nx
from sqlglot import exp

from sqlleaf import util, mappings, context, sqlglot_lineage, exception

logger = logging.getLogger("sqleaf")


def new_graph() -> nx.MultiDiGraph:
    """
    A graph has attributes along with its node and edges.
    """
    return nx.MultiDiGraph(attrs=GraphAttributes())


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

        self.statement_original = statement
        self.statement_transformed = None
        self.set_properties(statement)
        self.set_statement(statement)

        logger.debug(f"Created structs.Query: {self.__class__}")

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        if self.parent_query:
            index = self.parent_query.get_statement_index()
            return index + ':' + str(self.statement_index)
        else:
            return str(self.statement_index)

    def set_properties(self, statement):
        self.property_names = []
        table_properties = statement.args.get("properties")
        if table_properties:
            self.property_names = [str(p) for p in table_properties.expressions]

    def set_statement(self, statement: exp.Expression):
        self.statement = statement
        text = statement.sql()
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

    def get_all_child_queries(self) -> t.List:
        """
        Fetch all the child queries recursively

        For example, a MERGE may contain several INSERT, UPDATE.
        """
        queries = []
        for child in self.child_queries:
            queries.extend(child.get_all_child_queries())
        return queries

    def determine_selected_columns(self, mapping: mappings.ObjectMapping) -> t.Dict:
        """
         Determine whether the selected columns exist inside the table's mapping.
        An error is thrown if any non-existent or invalid columns are used.

        Parameters:
            mapping (sqlglot.MappingSchema): the mapping of table schemas

        Returns:
            child_columns: {col_name: {'kind': 'table', 'selected': False, 'default': '42'}, ...}
        """
        child_table = self.child_table
        # Get the 'CREATE TABLE' query for this query's child table
        if str(child_table).startswith("@"):
            child_table_query = mapping.find_query(kind='stage', table=child_table)
        else:
            child_table_query = mapping.find_query(kind='table', table=child_table)

        if not child_table_query:
            raise exception.SqlLeafException(message="Unknown table", table=str(child_table))

        statement = self.statement
        child_columns = child_table_query.get_columns()
        unknown_columns = util.unique(statement.named_selects - child_columns.keys())

        if unknown_columns:
            raise exception.SqlLeafException(
                message=f"Unknown columns used in SELECT: {list(unknown_columns)}",
                table=str(child_table),
            )

        if "*" in child_columns.keys():
            # TODO: shouldn't this check statement.named_selects instead?
            raise exception.SqlLeafException(message="Statement has unresolved star column", table=str(child_table))

        # Set the query's columns as being selected (required by sqlglot's lineage())
        for col_name, col_props in child_columns.items():
            col_props["selected"] = col_name in statement.named_selects

        return child_columns

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
    def __init__(self, expr: exp.Merge, dialect: str, statement_index: int):
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
        self.collect_and_transform_child_expressions(expr)

    def collect_and_transform_child_expressions(self, expr: exp.Merge):
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
                    into=merge.child_table,
                )
                for cte in new_ctes:
                    insert_expr = insert_expr.with_(alias=cte["alias"], as_=cte["as_"])

                insert_query = InsertQuery(expr=insert_expr, dialect=self.dialect, statement_index=i)
                self.add_child_query(insert_query)


class InsertQuery(Query):
    def __init__(self, expr: exp.Insert, dialect: str, statement_index: int):
        super().__init__(
            kind="insert",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(expr),
        )


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

        # The "SET" expressions need to be converted.
        # For the update command, it'll be a list of EQ expressions, but the select
        # should contain aliased columns.
        new_expressions = []
        for expr in statement.expressions:
            if isinstance(expr, exp.EQ) and isinstance(expr.left, exp.Column):
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
        insert_statement = exp.insert(expression=select_statement, into=statement.this)
        self.set_statement(insert_statement)


class CTASQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        columns: t.Dict[str, t.Dict[str, str]],
        statement_index: int,
    ):
        super().__init__(
            kind="ctas",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement),
        )
        self.columns = columns

    def get_columns(self) -> t.Dict[str, t.Dict[str, str]]:
        return self.columns

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {name: str(props["kind"]) for name, props in self.columns.items()}
        return columns


class ViewQuery(Query):
    def __init__(
        self,
        statement: exp.Create,
        dialect: str,
        columns: t.Dict[str, t.Dict[str, str]],
        statement_index: int,
    ):
        super().__init__(
            kind="view",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement),
        )
        self.columns = columns

    def get_columns(self) -> t.Dict[str, t.Dict[str, str]]:
        return self.columns

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {name: str(props["kind"]) for name, props in self.columns.items()}
        return columns


class TableQuery(Query):
    def __init__(self, statement: exp.Create, dialect: str, mapping, statement_index: int):
        super().__init__(
            kind="table",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(statement.this),
            has_statement = False,
        )
        self.property_names = []
        self.column_defs = []

        self.set_column_defs(mapping)

    def set_column_defs(self, mapping: mappings.ObjectMapping):
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
        table_properties = statement.args["properties"]
        if table_properties:
            self.property_names = [str(p) for p in table_properties.expressions]

            inherited_columns = self.find_inherited_columns(table_properties, mapping)
            like_columns = self.find_like_columns(table_properties, mapping)

            columns += inherited_columns + like_columns

        self.column_defs = columns

    def find_inherited_columns(self, table_properties: exp.Expression, mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b INHERITS (a)'
        """
        columns = []
        inherited_props = list(table_properties.find_all(exp.InheritsProperty))

        for inh_prop in inherited_props:
            inh_table = inh_prop.find(exp.Table)
            inh_table_query = mapping.find_query(kind='table', table=inh_table)
            columns.extend(inh_table_query.column_defs)

        return columns

    def find_like_columns(self, table_properties: exp.Expression, mapping: mappings.ObjectMapping) -> t.List[exp.ColumnDef]:
        """
        Search for tables referenced as 'CREATE TABLE b LIKE a'
        """
        columns = []
        like_props = list(table_properties.find_all(exp.LikeProperty))

        for like_prop in like_props:
            like_table = like_prop.this
            props = sorted(
                [p for p in like_prop.expressions if type(p) is exp.Property],
                reverse=True,
            )
            include_props = {
                "defaults": False,
                "generated": False,
                "identity": False,
            }

            for prop in sorted(props, reverse=True):
                if prop.this == "INCLUDING":
                    val = str(prop.args["value"])
                    self.set_props(val, props=include_props, to_include=True)
                elif prop.this == "EXCLUDING":
                    val = str(prop.args["value"])
                    self.set_props(val, props=include_props, to_include=False)

            parent_table = mapping.find_query(kind='table', table=like_table)
            parent_columns = parent_table.column_defs
            # TODO: copy parent_table, change column props based on props
            for col_def in parent_columns:
                new_col = col_def.copy()
                if not include_props["defaults"]:
                    # Delete the default column
                    if default := new_col.find(exp.DefaultColumnConstraint):
                        default.parent.pop()
                        logger.debug("Excluded column default: %s", str(default))
                columns.append(new_col)
                # TODO: below
                # if col is identity and include_props, include
                # if col is generated and include_props, include

        return columns

    def get_column_names_with_types(self) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema

        Returns: {'col1': 'INT', 'col2': 'VARCHAR'}
        """
        columns = {c.name: str(c.kind) for c in self.column_defs}
        return columns

    def get_columns(self) -> t.Dict[str, t.Dict[str, str]]:
        columns = {}
        for c in self.column_defs:
            default = c.find(exp.DefaultColumnConstraint)
            if default:
                default = default.this

            columns[c.name] = {
                "default": default,
                "kind": str(c.kind),
            }
        return columns

    def set_props(self, val: str, props: t.Dict, to_include: bool = False):
        if val == "ALL":
            props["defaults"] = to_include
            props["generated"] = to_include
            props["identity"] = to_include
        elif val == "DEFAULTS":
            props["defaults"] = to_include
        elif val == "GENERATED":
            props["generated"] = to_include
        elif val == "IDENTITY":
            props["identity"] = to_include
        return props


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

    def get_columns(self) -> t.Dict[str, t.Dict[str, str]]:
        return self.columns


class CopyQuery(Query):
    def __init__(self, expr: exp.Copy, dialect: str, mapping: mappings.ObjectMapping, statement_index: int):
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

        self.set_as_insert(expr, dialect, mapping)

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

    def set_as_insert(self, expr, dialect, mapping):
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

        child_columns = mapping.find_columns_for_table(table=source_table)
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
            named_columns = {s.alias_or_name: {"default": None, "kind": s.type or "UNKNOWN"} for s in expr_insert.selects}

            child_table_query = mapping.find_query(kind='stage', table=child_table)
            child_table_query.columns = named_columns

        # We don't worry about `self.is_source_a_stage` here as that is handled in the process_column() later

        self.set_statement(expr_insert)


class PutQuery(Query):
    def __init__(self, expr: exp.Put, dialect: str, mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="put",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=expr.this,
        )
        self.source = expr.name
        self.target = expr.args['target'].name


################################ NODES ################################


class NodeAttributes:
    def __init__(
        self,
        expr: exp.Expression,
        data_type: exp.DataType,
        ctx: context.NodeContext,
        column: str,
        table: str = "",
        schema: str = "",
        catalog: str = "",
        kind: str = "",
        table_type: str = "",
        table_properties: t.List = None,
    ):
        self.expr = expr
        self.data_type = str(data_type)  # TODO: could we just assign expr.type = data_type and remove this?
        self.column = column
        self.kind = kind
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.table_type = table_type
        self.table_properties = sorted(table_properties) if table_properties else []
        self.ctx = ctx

        logger.debug(f"structs.NodeAttributes: Created Node: {self.__class__}, Name: {self.full_name}")

    # Allows the class to be used a networkx node
    def __hash__(self):
        return hash(self.full_name)

    def wrap(self, name: str):
        return f"{self.kind}[{name}]"

    @property
    def full_name(self):
        return self.wrap(f"{self.column} type={self.data_type}")

    @property
    def friendly_name(self):
        return f"{self.kind}[{self.column}]"

    @property
    def id(self):
        # TODO: add correct fields
        fields = [
            self.catalog,
            self.schema,
            self.table,
            self.column,
            self.data_type,
            self.table_type,
            util.type_name(self.expr),
        ]
        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "catalog": self.catalog,
            "schema": self.schema,
            "table": self.table,
            "column": self.column,
            "data_type": self.data_type,
            "kind": self.kind,
            "table_type": self.table_type,
            "table_properties": self.table_properties,
        }


class LiteralNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="literal",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )

    @property
    def full_name(self):
        name = self.column.replace("'", '"')
        return self.wrap(
            f"{name} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = self.column.replace("'", '"')
        return f"{self.kind}[{name}]"


class ColumnNode(NodeAttributes):
    def __init__(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        processor_ctx: ProcessorContext,
        ctx: context.NodeContext,
    ):
        expr: exp.Column = processor_ctx.expr

        super().__init__(
            kind="column",
            catalog=catalog,
            schema=schema,
            table=table,
            column=column,
            data_type=processor_ctx.data_type,
            expr=expr,
            table_type=self._table_type(catalog, schema, table, processor_ctx),
            table_properties=processor_ctx.query.property_names,
            ctx=ctx,
        )

    def _table_type(self, catalog, schema, table, processor_ctx):
        """
        Figure out the table's type (view/table) by inspecting the original query in the mapping.
        """
        if processor_ctx.node and processor_ctx.node.is_cte:
            return "cte"

        tokens = [catalog, schema, table]
        name = ".".join([tok for tok in tokens if tok])
        tab = exp.to_table(name, dialect=processor_ctx.query.dialect)
        query = processor_ctx.mapping.find_query(kind='table', table=tab)
        if not query:
            query = processor_ctx.mapping.find_query(kind='stage', table=tab)

        if query.kind == 'ctas':
            return 'table'
        return query.kind

    def get_name(self):
        tokens = [self.catalog, self.schema, self.table, self.column]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        if self.table_type == 'cte':
            # A CTE name can be reused across statements
            return self.wrap(f"{self.get_name()} type={self.data_type} statement={self.ctx.statement_index} kind={self.table_type}")
        else:
            return self.wrap(f"{self.get_name()} type={self.data_type} kind={self.table_type}")

    @property
    def friendly_name(self):
        return self.wrap(self.get_name())


class FunctionNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="function",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=processor_ctx.expr.key,
            ctx=ctx,
        )

    @property
    def full_name(self):
        name = f"{self.column}()".upper()
        return self.wrap(
            f"{name} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        name = f"{self.column}()".upper()
        return self.wrap(name)


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        name: str,
        schema: str,
        processor_ctx: ProcessorContext,
        ctx: context.NodeContext,
    ):
        super().__init__(
            kind="udf",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            schema=schema,
            column=name,
            ctx=ctx,
        )

    def get_name(self):
        tokens = [self.schema, self.column]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        return self.wrap(
            f"{self.get_name()} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap(f"{self.get_name()}()".upper())


class JsonPathNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        expr: exp.JSONExtract = processor_ctx.expr

        self.selectors = self.json_selectors(expr)
        self.selector = "".join([str(s) for s in self.selectors])
        self.selector_depth = len(self.selectors)

        super().__init__(
            kind="jsonpath",
            data_type=processor_ctx.data_type,
            expr=expr,
            column=self.selector,
            ctx=ctx,
        )

    def json_selectors(self, expr: exp.JSONExtract):
        """
        Collect all the JSON path elements recursively.
        e.g.
            SELECT my_json -> 'a' -> 'b'
        produces
            ['a', 'b']
        """
        elements = list(expr.expression.find_all(exp.JSONPathKey))

        left = expr.left
        while isinstance(left, (exp.JSONExtract, exp.JSONExtractScalar)):
            elements.extend(list(left.expression.find_all(exp.JSONPathKey)))
            left = left.left
        elements.reverse()

        return elements

    @property
    def full_name(self):
        return self.wrap(f"{self.column} depth={self.selector_depth}")


class VariableNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="variable",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=processor_ctx.node.name,
            ctx=ctx,
        )


class StarNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="star",
            data_type=exp.DataType.build("UNKNOWN"),
            expr=processor_ctx.expr,
            column="*",
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class VarNode(NodeAttributes):
    def __init__(self, processor_ctx, ctx: context.NodeContext):
        super().__init__(
            kind="var",
            data_type=exp.DataType.build("NULL"),
            expr=processor_ctx.expr,
            column=processor_ctx.expr.name,
            ctx=ctx,
        )


class NullNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="null",
            data_type=exp.DataType.build("NULL"),
            expr=processor_ctx.expr,
            column="null",
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(
            f"{self.column} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )

    @property
    def friendly_name(self):
        return self.wrap("NULL")


class SequenceNode(NodeAttributes):
    def __init__(self, name: str, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="sequence",
            data_type=exp.DataType.build("INT"),
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )


class WindowNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        super().__init__(
            kind="window",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=processor_ctx.expr.this.sql(),
            ctx=ctx,
        )


class StageNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        expr: exp.Var = processor_ctx.expr

        if str(expr).startswith("@"):
            if not str(expr).startswith('@"'):
                # Set to uppercase only if not double-quoted
                expr.set("this", str(expr).upper())

        super().__init__(
            kind="stage",
            data_type=None,
            expr=expr,
            column=expr.name.removeprefix("@").replace('"', ""),
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class FileNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        expr: exp.Literal = processor_ctx.expr
        filename = expr.this.removeprefix("file://")
        super().__init__(
            kind="file",
            data_type=None,
            expr=processor_ctx.expr,
            column=filename,
            ctx=ctx,
        )

    @property
    def full_name(self):
        return self.wrap(f"{self.column}")


class IntervalNode(NodeAttributes):
    def __init__(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        expr: exp.Interval = processor_ctx.expr
        name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        super().__init__(
            kind="interval",
            data_type=processor_ctx.data_type,
            expr=processor_ctx.expr,
            column=name,
            ctx=ctx,
        )
        print()

    @property
    def full_name(self):
        return self.wrap(
            f"{self.column} type={self.data_type} node_depth={self.ctx.node_depth} statement={self.ctx.statement_index} select={self.ctx.select_index} func_depth={self.ctx.function_depth} func_arg={self.ctx.function_arg_index}"
        )


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Query,
        select_idx: int,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query

        # These positions help unique identify syntax inside a set of SQL statements
        self.select_idx = select_idx  # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b', 'c')
        self.path_idx = path_idx  # <TODO: can I rely on the query hash instead?> The position of this edge inside a set of identical edges (e.g. two edges between nodes A->B). This can occur if the same query is used across multiple files.

        self.create_edge_id()

    def create_edge_id(self):
        # TODO: get the correct prefix from the parent queries
        prefix = "todo_sp_or_udf"
        edge_id = ":".join(
            [
                str(s)
                for s in [
                    prefix,
                    self.parent.full_name,
                    self.child.full_name,
                    self.select_idx,
                    self.path_idx,
                ]
            ]
        )
        self.id = "edge:" + util.short_sha256_hash(edge_id)

    def to_dict(self):
        result = {
            "id": self.id,
            "parent": {
                "id": self.parent.id,
                "full_name": self.parent.full_name,
            },
            "child": {
                "id": self.child.id,
                "full_name": self.child.full_name,
            },
            "indices": {
                "select_idx": self.select_idx,
                "path_idx": self.path_idx,
            },
            "query": {
                "id": self.query.id
            },
        }
        return result


class GraphAttributes:
    def __init__(self):
        self.queries: t.List[Query] = []

    def add_query(self, query: Query):
        self.queries.append(query)


class LineagePath:
    def __init__(self, root: str, hops: t.List[EdgeAttributes]):
        self.root = root
        self.hops = hops
        self.path_length = len(hops)
        self.path_id = "path:" + util.short_sha256_hash(":".join(self.get_edge_ids()))

        for i, edge in enumerate(self.hops):
            edge.path_id = self.path_id
            edge.path_hop = i

    def node_hops(self) -> t.List[NodeAttributes]:
        """
        Return the list of nodes in this path.
        """
        hops = [self.hops[0].parent, self.hops[0].child]
        for hop in self.hops[1:]:
            hops.append(hop.child)
        return hops

    def get_edge_ids(self):
        """
        In order to distinguish between multiple edges that are part of the same path,
        we need to create a unique id based off data that differentiates them.
        This is done using the edges' "id" attribute.
        """
        return [edge.id for edge in self.hops]

    def to_dict(self):
        return {
            "id": self.path_id,
            "length": len(self.hops),
            "hops": [edge.id for edge in self.hops],
        }


@dataclass(frozen=True)
class ProcessorContext:
    graph: nx.MultiDiGraph
    mapping: mappings.ObjectMapping
    query: Query
    expr: exp.Expression
    data_type: exp.DataType = None
    node: sqlglot_lineage.Node = None
    child_node_attrs: NodeAttributes = None
    # Override the data_type if needed
    new_data_type: InitVar[exp.DataType] = None

    def __post_init__(self, new_data_type: exp.DataType = None):
        # Called via replace() or if a new object is instantiated
        if new_data_type:
            expr_type = new_data_type
        else:
            if (not self.expr.type or self.expr.type == exp.DataType.Type.UNKNOWN) and self.expr.parent:
                expr_type = self.expr.parent.type
            else:
                expr_type = self.expr.type

        unwrapped_expr = util.unwrap_expression(self.expr)

        object.__setattr__(self, "data_type", expr_type)
        object.__setattr__(self, "expr", unwrapped_expr)


class LineageBuilder:
    # A registry to store subclasses
    _dialects = {}
    dialect = ""

    def get_expression_processors(self) -> t.Dict:
        """
        These are processed in the order they are defined.
        This is due to subclasses generally needing to be processed first.
        """
        skip = (exp.DataType, exp.Identifier)
        return {
            exp.Placeholder: self.process_placeholder,
            exp.Array: self.process_array,
            (exp.JSONExtract, exp.JSONBExtract): self.process_json,
            exp.Window: self.process_window,
            (exp.Literal, exp.Boolean): self.process_literal,
            exp.Star: self.process_star,
            exp.Cast: self.process_cast,
            exp.Null: self.process_null,
            exp.Neg: self.process_neg,
            exp.Anonymous: self.process_anonymous,
            exp.Case: self.process_case,
            exp.Var: self.process_var,
            exp.Func: self.process_function,
            exp.Binary: self.process_binary,
            # exp.Identifier: self.process_identifier,
            exp.Column: self.process_column,
            exp.Table: self.process_table,
            exp.WithinGroup: self.process_within_group,
            exp.Select: self.process_select,
            exp.Interval: self.process_interval,

            skip: self.skip,
        }

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        LineageBuilder._dialects[cls.dialect] = cls

    @classmethod
    def from_dialect(cls, class_name, *args, **kwargs):
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if target_class:
            return target_class()
        else:
            return LineageBuilder()

    def get_processor(self, expr: exp.Expression):
        """
        Find the processor for the expression.
        We iterate over the list in order because earlier processors (usually subclasses)
        often take precedence.
        """
        for types, processor in self.get_expression_processors().items():
            if isinstance(expr, types):
                return processor
        return None

    def walk_tree_and_build_graph(
        self,
        processor_ctx: ProcessorContext,
        ctx: context.NodeContext,
    ) -> t.List[NodeAttributes]:
        """
        Collect the leaves of an expression so that we can get the full set of data sources and function arguments
        for a particular column.
        """
        nodes_created = []
        expr = processor_ctx.expr
        child_node_attrs = processor_ctx.child_node_attrs

        logger.debug("walk_tree_and_build_graph(): %s", type(expr))

        processor_func = self.get_processor(expr)
        if not processor_func:
            raise ValueError(f"Unknown expression type: {type(expr)}")

        parent_node_attrs, children = processor_func(processor_ctx=processor_ctx, ctx=ctx)

        if parent_node_attrs:
            self.add_nodes_with_edge_to_graph(
                parent_node_attrs,
                child_node_attrs,
                processor_ctx.graph,
                processor_ctx.query,
                ctx,
            )
            nodes_created.append(parent_node_attrs)
        else:
            # Re-use the parent
            parent_node_attrs = child_node_attrs

        # For every function arg, add the node
        child_ctx = replace(ctx, function_depth=ctx.function_depth + 1)

        for child_expr in children:
            child_processor_ctx = replace(processor_ctx, expr=child_expr, child_node_attrs=parent_node_attrs)
            nodes = self.walk_tree_and_build_graph(child_processor_ctx, child_ctx)
            nodes_created.extend(nodes)
            child_ctx = replace(child_ctx, function_arg_index=child_ctx.function_arg_index + 1)

        return nodes_created

    def process_function(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        node_attrs = FunctionNode(processor_ctx, ctx)
        args = util.get_function_args(expr=processor_ctx.expr)
        return node_attrs, args

    def process_placeholder(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        CREATE PROCEDURE proc(v_amount INT) AS
        SELECT v_amount     <-- placeholder
        """
        args = processor_ctx.query.parent_query.args
        try:
            col_type = [arg["type"] for arg in args if arg["name"] == processor_ctx.node.name][0]
        except IndexError:
            col_type = "UNKNOWN"

        processor_ctx = replace(processor_ctx, new_data_type=exp.DataType.build(col_type))
        node_attrs = VariableNode(processor_ctx, ctx)
        return node_attrs, []

    def process_array(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in processor_ctx.expr.expressions]
        values = '{' + ','.join(values) + '}'
        node_attrs = LiteralNode(name=values, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_window(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        window_expr: exp.Window = processor_ctx.expr

        if window_expr.this.key in ["rownumber", "rank"]:
            processor_ctx = replace(processor_ctx, new_data_type=exp.DataType.build("INT"))

        node_attrs = WindowNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_literal(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        select 'hello' as greeting
        """
        expr: exp.Literal = processor_ctx.expr
        node_attrs = LiteralNode(name=expr.sql(comments=False), processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_star(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        select count(*) as cnt
        """
        node_attrs = StarNode(processor_ctx, ctx)
        return node_attrs, []

    def process_null(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        node_attrs = NullNode(processor_ctx, ctx)
        return node_attrs, []

    def process_cast(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT col1::timestamp AS col1_time
        """
        processor_ctx_to = replace(processor_ctx, new_data_type=processor_ctx.expr.to)
        return self.process_function(processor_ctx_to, ctx)

    def process_neg(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT -10
        """
        expr: exp.Literal = processor_ctx.expr
        node_attrs = LiteralNode(name="-" + expr.name, processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_anonymous(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        expr: exp.Anonymous = processor_ctx.expr

        if isinstance(expr.parent, (exp.Dot,)):
            # Postgres UDFs don't support catalogs
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
            full_name = f"{schema}.{function}"
        else:
            # e.g. The PG sequence function nextval('serial') is anonymous
            schema = None
            function = expr.name
            full_name = function

        # Process a sequence
        # TODO: add per-dialect processors
        if not schema and function in [
            "nextval",
            "currval",
            "setval",
        ]:  # and dialect == 'postgres'
            # 'lastval()' is not yet supported since it requires state
            seq_name_expr: exp.Literal = expr.args["expressions"][0]

            # Ensure the sequence exists
            seq_table = exp.table_(table=seq_name_expr.name, db=schema)
            if not processor_ctx.mapping.find_query(kind='sequence', table=seq_table):
                logger.warning(f"Sequence '{full_name}' not found.")

            node_attrs = SequenceNode(name=seq_name_expr.name, processor_ctx=processor_ctx, ctx=ctx)
            return node_attrs, []

        # Process a UDF
        node_args = list(expr.flatten())
        node_attrs = UserDefinedFunctionNode(name=function, schema=schema, processor_ctx=processor_ctx, ctx=ctx)

        table_expr = exp.table_(table=function, db=schema)
        udf_obj = processor_ctx.mapping.find_query(kind='udf', table=table_expr)

        # if the udf has a return_expr, insert it in here
        # if it's a literal, set the parent of 'this' as the return expr. Discard the args in lineage, but record in object
        if udf_obj:
            if isinstance(udf_obj.return_expr, exp.Literal):
                node_args = [udf_obj.return_expr]

        return node_attrs, node_args

    def process_within_group(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name
        """
        expr: exp.WithinGroup = processor_ctx.expr
        processor_ctx = replace(processor_ctx, expr=expr.this)

        parent, children = self.process_function(processor_ctx, ctx)
        children = list(expr.expression.find_all(exp.Column))  # expr.expression is type(exp.Order)
        return parent, children

    def process_select(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT (SELECT 1) AS name
        """
        return None, []

    def process_case(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT CASE WHEN count(*) > 1 THEN 1 ELSE 0 END AS my_var
        """
        # If no default is specified, the default is NULL (via ANSI SQL) TODO: however in PL/pgsql it's an error instead; check for this
        expr: exp.Case = processor_ctx.expr
        default = expr.args.get("default", exp.Null())
        thens = [if_expr.args.get("true") or if_expr.args.get("false") for if_expr in expr.args["ifs"]]
        children = [default] + thens
        return None, children

    def process_binary(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        SELECT 1 + 2 AS age
        """
        expr: exp.Binary = processor_ctx.expr
        if isinstance(expr, exp.Dot):
            # Process this as a UDF
            logger.debug("Found exp.Dot inside exp.Binary")
            processor_ctx = replace(processor_ctx, expr=expr.right)
            return self.process_anonymous(processor_ctx, ctx)

        node_attrs = FunctionNode(processor_ctx, ctx)
        args = [expr.left, expr.right]

        return node_attrs, args

    def process_var(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """ """
        node_attrs = VarNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def process_column(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        expr: exp.Column = processor_ctx.expr
        if is_node_a_placeholder(expr=expr, query=processor_ctx.query):
            # The actual placeholder is processed elsewhere
            return None, []

        node_attrs = ColumnNode(
            catalog=expr.catalog,
            schema=expr.db,
            table=expr.table,
            column=expr.name,
            processor_ctx=processor_ctx,
            ctx=ctx,
        )

        ### Add the column's default expression as lineage
        # TODO: make this optional via a CLI flag

        return node_attrs, []

    def process_table(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        logger.debug(f"Skipping exp.Table: {str(processor_ctx.expr)}")
        return None, []

    def process_json(self, processor_ctx: ProcessorContext, ctx: context.NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        expr: exp.JSONExtract = processor_ctx.expr
        node_attrs = JsonPathNode(name=expr.name, processor_ctx=processor_ctx, ctx=ctx)

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        return node_attrs, [source]

    def process_interval(self, processor_ctx: ProcessorContext, ctx: context.NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        node_attrs = IntervalNode(processor_ctx=processor_ctx, ctx=ctx)
        return node_attrs, []

    def skip(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        logger.debug("Skipping expression {}".format(str(processor_ctx.expr)))
        return processor_ctx.child_node_attrs, []

    def add_nodes_with_edge_to_graph(
        self,
        parent_node_attrs,
        child_node_attrs,
        graph: nx.MultiDiGraph,
        query: Query,
        ctx: context.NodeContext,
    ):
        """
        Add two nodes and an edge between them to the graph.
        """
        p_attrs = self.add_node_if_not_exists(parent_node_attrs, graph)
        c_attrs = self.add_node_if_not_exists(child_node_attrs, graph)

        if p_attrs and c_attrs:
            p_full_name = p_attrs.full_name
            c_full_name = c_attrs.full_name

            edge_attrs = EdgeAttributes(
                parent=p_attrs,
                child=c_attrs,
                query=query,
                select_idx=ctx.select_index,
                path_idx=-1,  # -1 is temp
            )
            graph.add_edge(p_full_name, c_full_name, attrs=edge_attrs)
            logger.debug(f"Added edge between {p_full_name} [{id(p_attrs)}] -> {c_full_name} [{id(c_attrs)}]")

    def add_node_if_not_exists(self, node_attrs: NodeAttributes, graph: nx.MultiDiGraph) -> NodeAttributes:
        """
        Add a node to the graph if it doesn't already exist.

        We need to re-use the existing node attributes so that the edge attribute objects don't refer to different-but-same-named node attributes.
        """
        if not node_attrs:
            return None

        node_name = node_attrs.full_name

        if graph.has_node(node_name):
            return graph.nodes[node_name]['attrs']

        graph.add_node(node_name, attrs=node_attrs)
        return node_attrs


class PostgresLineageBuilder(LineageBuilder):
    dialect = "postgres"


class SnowflakeLineageBuilder(LineageBuilder):
    dialect = "snowflake"

    def process_put(self, processor_ctx: ProcessorContext, ctx: context.NodeContext) -> t.Tuple[NodeAttributes, t.List[exp.Expression]]:
        """
        PUT 'file:///tmp/data/mydata.csv' @my_int_stage;
        - Creates two nodes: FileNode and StageNode
        """
        # This steps outside the 'process_node_objects()' main method, as
        # adding logic inside the default functions is too messy.
        # We may need to return to this later.
        file_ctx = replace(processor_ctx, expr=processor_ctx.expr.args['this'])
        stage_ctx = replace(processor_ctx, expr=processor_ctx.expr.args['target'])

        file_node = FileNode(processor_ctx=file_ctx, ctx=ctx)
        stage_node = StageNode(processor_ctx=stage_ctx, ctx=ctx)

        self.add_nodes_with_edge_to_graph(file_node, stage_node, processor_ctx.graph, processor_ctx.query, ctx)

    def process_column(self, processor_ctx: ProcessorContext, ctx: context.NodeContext):
        """
        If the source is actually a Stage, don't try to create a Column.
        """
        query = processor_ctx.query
        if isinstance(query, CopyQuery):
            if query.is_source_a_stage:
                stage_name: exp.Var = query.source.this
                stage_ctx = replace(processor_ctx, expr=stage_name)
                parent_node_attrs = StageNode(processor_ctx=stage_ctx, ctx=ctx)
                return parent_node_attrs, []

        return super().process_column(processor_ctx, ctx)

def is_node_a_placeholder(expr: exp.Column, query: Query) -> bool:
    """
    Check if a Column is actually a Placeholder.

    For example, given
        CREATE PROCEDURE purchase(v_amount INT) AS
            SELECT v_amount as amount

    the 'v_amount' inside the SELECT will be a Column, but instead it should be a Placeholder.
    This is caused by sqlglot_lineage.lineage()
    """
    if query.parent_query and isinstance(query.parent_query, ProcedureQuery):
        args = query.parent_query.args
        arg_names = [a["name"] for a in args]
        if expr.name in arg_names:
            logger.debug(f"Skipping Column {expr.name} as it is a Placeholder")
            return True
    return False
