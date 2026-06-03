from __future__ import annotations

import logging
import typing as t

import sqlglot
from sqlglot import TokenType, exp

from sqlleaf import exception, mappings, util
from sqlleaf.typing import SourceExprType, TargetExprType

logger = logging.getLogger("sqlleaf")


class Query:
    def __init__(
        self,
        kind: str,
        dialect: str,
        statement: exp.Expr,
        child_object: TargetExprType,
        statement_index: int,
    ):
        self.kind = kind
        self.dialect = dialect
        self.child_object = child_object  # The target table
        self.parent_query = None
        self.child_queries = []
        self.column_defs: t.List[exp.ColumnDef] = []
        self.property = ""

        # Remove comments at initialisation
        for expr in statement.walk():
            expr.pop_comments()

        self.statement_index = statement_index  # The position of this query within a list of queries
        self.statement_original = statement
        self.statement_transformed: exp.Expr

        self.statement = statement
        self.set_statement(self.statement_original)

        self.source: SourceExprType
        self.target: TargetExprType = child_object

        logger.debug(f"Created Query: {self.__class__}")

    def get_source(self) -> SourceExprType:
        return self.source

    def get_target(self) -> TargetExprType:
        return self.target

    def get_target_as_table(self) -> exp.Table:
        """
        For functions that only accept tables.
        """
        if not isinstance(self.target, exp.Table):
            raise exception.SqlLeafException(
                message=f"Expected the target object to be a table but it is a {type(self.target)}"
            )
        return self.target

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        if self.parent_query:
            index = self.parent_query.get_statement_index()
            return index + ":" + str(self.statement_index)
        else:
            return str(self.statement_index)

    def set_statement(self, statement: exp.Expr):
        self.statement = statement

    def get_ctes(self) -> t.List:
        return []

    def get_column_defs(self, include_system: bool = False) -> t.List:
        return []

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        # columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        # return columns
        # TODO: remove from child classes?
        return {}

    @property
    def id(self) -> str:
        return "query:" + util.short_sha256_hash(self.statement_original.sql() + ":" + str(self.statement_index))

    def set_to_original(self):
        """
        Convert the Query back to its original statement.

        This is needed for CTAS/View queries after they transform into Inserts.
        This is the inverse of functions like set_as_insert()
        """
        self.set_statement(statement=self.statement_original)

    def add_child_query(self, child_query):
        child_query.parent_query = self
        self.child_queries.append(child_query)

    def add_child_queries(self, child_queries: t.List):
        for query in child_queries:
            self.add_child_query(query)

    def get_all_queries(self, types: t.Tuple | None = None):
        """
        Collect all queries (self + children recursively), optionally filtered by type.
        """
        queries = [self]

        for child in self.child_queries:
            queries.extend(child.get_all_queries(types))

        if types:
            queries = [q for q in queries if isinstance(q, types)]

        return queries

    def get_root_query(self):
        return self if not self.parent_query else self.parent_query.get_root_query()

    def get_selected_column_names(self) -> t.List[str]:
        if isinstance(self.statement.expression, exp.Values):
            return [s.name for s in self.statement.this.expressions]
        return self.statement.named_selects

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.statement_index,
        }
        return result


class DeleteQuery(Query):
    def __init__(self, expr: exp.Delete, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="delete",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=expr.this,
        )

    def get_ctes(self):
        if "with_" in self.statement.args:
            return self.statement.args["with_"].expressions
        return []


class MergeQuery(Query):
    def __init__(self, expr: exp.Merge, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="merge",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=expr.this,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])


class SelectQuery(Query):
    def __init__(self, expr: exp.Select, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="select",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=util.get_table(expr),
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])


class InsertQuery(Query):
    def __init__(
        self,
        expr: exp.Insert,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
    ):
        if not table:
            table = util.get_table(expr)
        super().__init__(
            kind="insert",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=table,
        )

    def get_ctes(self):
        return getattr(self.statement, "ctes", [])


class UpdateQuery(Query):
    def __init__(
        self,
        expr: exp.Update,
        dialect: str,
        object_mapping: mappings.ObjectMapping,
        statement_index: int,
        table: exp.Table | None = None,
    ):
        if not table:
            table = util.get_table(expr)
        super().__init__(
            kind="update",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=table,
        )
        self.only = table.args.get("only", False) if table else False  # Not available inside a MERGE

    def get_ctes(self):
        with_ = self.statement.args.get("with_", None)
        return with_.expressions if with_ else []


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
            child_object=util.get_table(statement),
        )
        self.column_defs: t.List[exp.ColumnDef] = columns
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherited_by: t.List[TableQuery] = []

        self.with_data: bool = True
        if props := statement.args["properties"]:
            if with_data := props.find(exp.WithDataProperty):
                self.with_data: bool = not with_data.args["no"]

        self.property: str = util.find_property(statement)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
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
            child_object=util.get_table(statement),
        )
        self.column_defs: t.List[exp.ColumnDef] = columns
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(statement)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns


class TableQuery(Query):
    def __init__(
        self, statement: exp.Create, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int
    ):
        super().__init__(
            kind="table",
            statement=statement,
            dialect=dialect,
            statement_index=statement_index,
            child_object=util.get_table(statement.this),
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        self.system_column_defs: t.List[exp.ColumnDef] = []
        self.inherits: t.List[TableQuery] = []
        self.inherited_by: t.List[TableQuery] = []

        self.property: str = util.find_property(statement)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs + self.system_column_defs if include_system else self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
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
            child_object=table,
        )
        self.schema = table.db
        self.procedure = table.name
        self.signature = str(statement.this)  # e.g. etl.my_proc(v_session_id VARCHAR)

        # TODO: support 'default'
        self.column_defs: t.List[exp.ColumnDef] = statement.this.expressions
        self.args = [  # e.g. {'name': 'v_session_id', 'type': 'VARCHAR'}
            {"name": str(col.this), "type": str(col.kind)} for col in statement.this.find_all(exp.ColumnDef)
        ]

        self.set_statement(statement)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns

    @property
    def id(self):
        return "procedure:" + util.short_sha256_hash(self.statement_original.sql())

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "signature": self.signature,
            "args": self.args,
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
            child_object=statement.this.this,
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
            child_object=statement.this,
        )
        self.property = util.find_property(statement)


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
            child_object=properties.args["table"],
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
            child_object=util.get_table(statement),
        )
        self.column_defs: t.List[exp.ColumnDef] = []
        # Needed due to a bug in sqlglot. Never access the table name via print()!
        #  as it prints double-double quotes
        stage_name = str(self.get_target().this)
        self.get_target().this.set("this", "@" + stage_name)
        self.get_target().this.set("quoted", False)

        self.property = util.find_property(statement)

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs


class CopyQuery(Query):
    def __init__(self, expr: exp.Copy, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        self.named_columns: t.List[str] = []

        # TODO: move these variables/types to SourceExpr/TargetExpr
        self.is_source_a_stage = False
        self.is_target_a_stage = False

        self.source, self.target = self.process(expr, dialect)
        # self.source = source
        # self.target = target

        # if not isinstance(expr.this.unnest(), exp.Values):
        #     child_object = self.target
        # else:
        #     child_object = self.target

        super().__init__(
            kind="copy",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=self.target,
        )

    def process(self, expr: exp.Copy, dialect: str) -> t.Tuple[SourceExprType, TargetExprType]:
        """
        Determine the source and target expressions of the query.
        """
        if dialect == "postgres":
            # Postgres treats STDOUT and STDIN the same
            if expr.args["kind"]:
                # COPY X FROM STDOUT/STDIN
                source = expr.args["files"][0]
                target = expr.args["this"]
                if isinstance(target, exp.Schema):
                    target = target.this
            else:
                # COPY X TO STDOUT/STDIN
                source = expr.args["this"]
                target = expr.args["files"][0]
                if isinstance(source, exp.Schema):
                    # Named columns were provided
                    # self.named_columns = [e.name for e in self.source.expressions]
                    source = source.this

        elif dialect == "snowflake":
            source = expr.args["files"][0]
            target = expr.args["this"]

        # It may be a subquery
        source = source.unnest()
        target = target.unnest()

        if dialect == "snowflake":
            self.configure_stage(expr)

        return source, target

    def configure_stage(self, expr: exp.Copy):
        """
        Normalize (uppercase) the name if we are a Snowflake stage.
        sqlglot only normalizes columns - see comments in `sqlglot.optimizer.normalize_identifiers()`
        """
        source = expr.args["files"][0]
        target = expr.args["this"]

        if str(source).startswith("@"):
            self.is_source_a_stage = True
            if not str(source).startswith('@"'):
                source.this.set("this", str(source).upper())

        elif str(target).startswith("@"):
            self.is_target_a_stage = True
            if not str(target).startswith('@"'):
                target.this.set("this", str(target).upper())


class UnloadQuery(Query):
    def __init__(self, expr: exp.Command, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        select_expr, to_location_expr = self._parse_expression(expr)

        super().__init__(
            kind="unload",
            statement=select_expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=to_location_expr,
        )
        self.source = select_expr

    def _parse_expression(self, statement: exp.Command) -> t.Tuple[exp.Select, exp.Literal]:
        """
        Parse an UNLOAD statement for Redshift.
        We parse this ourselves due to missing support in sqlglot.
        """
        # Syntax: "UNLOAD ('SELECT ...') TO ..."
        expected_tokens = [TokenType.L_PAREN, TokenType.STRING, TokenType.R_PAREN, TokenType.VAR, TokenType.STRING]
        actual_tokens = sqlglot.tokenize(statement.expression.name, dialect="redshift")

        # Basic validation - ensure the token types match
        for i in range(len(expected_tokens)):
            if expected_tokens[i] != actual_tokens[i].token_type:
                # This may be incorrect! Use the parser instead once available.
                raise exception.SqlLeafException(
                    message=f"Invalid syntax for UNLOAD expression: {statement.sql(dialect='redshift')}"
                )

        select_expr = sqlglot.parse_one(actual_tokens[1].text, dialect="redshift")
        if not isinstance(select_expr, exp.Select):
            raise exception.SqlLeafException(
                message=f"Invalid expression inside UNLOAD. Expected SELECT "
                f"but got: {select_expr.sql(dialect='redshift')}"
            )

        to_location = actual_tokens[4].text
        return select_expr, t.cast(exp.Literal, exp.convert(to_location))


class PutQuery(Query):
    def __init__(self, expr: exp.Put, dialect: str, object_mapping: mappings.ObjectMapping, statement_index: int):
        super().__init__(
            kind="put",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_object=expr.this,
        )
        # TODO: fix types below
        self.source = expr.name
        self.target = expr.args["target"].name


Q = t.TypeVar("Q", bound=Query)
