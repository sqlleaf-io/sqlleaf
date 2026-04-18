from __future__ import annotations
import logging
import typing as t
from dataclasses import dataclass, replace, InitVar

import networkx as nx
from sqlglot import exp

from sqlleaf import util, mappings, sqlglot_lineage, exception

logger = logging.getLogger("sqleaf")


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
        self.statement = None
        self.child_table = child_table  # The target table
        self.statement_index = statement_index  # The position of this query within a list of queries
        self.parent_query = None
        self.child_queries = []
        self.has_statement = has_statement  # Has a DML statement (Insert, Update, Merge)

        self.statement_original = statement
        self.statement_transformed = None
        self.set_properties(statement)
        self.set_statement(statement)

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

    def set_properties(self, statement):
        self.property_names = []
        table_properties = statement.args.get("properties")
        if table_properties:
            self.property_names = [str(p) for p in table_properties.expressions]

    def set_statement(self, statement: exp.Expression):
        if not self.statement:
            # Remove comments at initialisation
            for expr in statement.walk():
                expr.pop_comments()

        self.statement = statement.copy()
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
            all_queries.extend([q for q in all_queries if types and isinstance(q, types)])

        return all_queries

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.statement_index,
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

    def get_ctes(self):
        return getattr(self.statement, 'ctes', [])


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

    def get_ctes(self):
        return getattr(self.statement, 'ctes', [])


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

    def get_ctes(self):
        return getattr(self.statement, 'ctes', [])


class UpdateQuery(Query):
    def __init__(self, expr: exp.Update, dialect: str, statement_index: int):
        super().__init__(
            kind="update",
            statement=expr,
            dialect=dialect,
            statement_index=statement_index,
            child_table=util.get_table(expr),
        )

    def get_ctes(self):
        with_ = self.statement.args.get('with_', None)
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
        self.property_names = []
        self.column_defs = []

    def get_column_defs(self) -> t.List[exp.ColumnDef]:
        return self.column_defs

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

        self.set_statement(expr)

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
