from __future__ import annotations

import logging
import typing as t

if t.TYPE_CHECKING:
    from sqlleaf.models.query import QueryHolder

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types

from sqlleaf import exception, mappings, util
from sqlleaf.typing import SourceExprType, SourceInfo, SqlObjectType, TargetExprType, TargetInfo

logger = logging.getLogger("sqlleaf")


class Query:
    KIND: str = ""

    def __init__(
        self,
        dialect: str,
        statement: exp.Expr,
        statement_index: int,
        object_mapping: mappings.ObjectMapping,
        source_info: SourceInfo | None,
        target_info: TargetInfo,
        skip_type_annotation: bool = False,
    ):
        self.kind = self.KIND
        self.dialect = dialect
        self.object_mapping = object_mapping
        self.parent_query = None
        self.child_queries = []
        self.column_defs: t.List[exp.ColumnDef] = []
        self.property = ""

        # Remove comments at initialization
        for expr in statement.walk():
            expr.pop_comments()

        if skip_type_annotation:
            # Prevent overwriting the types with UNKNOWN if they've already been annotated
            annotate_types(statement, dialect=dialect, schema=object_mapping)

        self.statement: exp.Expr = statement
        self.statement_index = statement_index  # The position of this query within a list of queries

        self.source_info = source_info
        self.target_info = target_info

        logger.debug(
            f"Created new query. Query => {self.__class__.__name__} | SourceType => {self.source_info and self.source_info.type.name} | TargetType => {self.target_info and self.target_info.type.name}"
        )

    def set_holder(self, holder: QueryHolder):
        self.holder = holder

    def _determine_expression_type(self, expr: exp.Expr | t.List[exp.Expr], dialect: str) -> SqlObjectType:
        """
        Determine the type of object that an expression represents.
        For example, the literal "/tmp/data.csv" is of type FILE; identifier "STDIN" is of type STREAM.
        """
        if isinstance(expr, exp.Literal):
            _type = SqlObjectType.DYNAMODB if expr.this.lower().startswith("dynamodb://") else SqlObjectType.FILE

        elif isinstance(expr, exp.Identifier):
            if expr.name.lower() in ["stdin", "stdout"]:
                _type = SqlObjectType.STREAM
            elif expr.name.lower() in ["program"]:
                _type = SqlObjectType.PROGRAM
            else:
                raise exception.InvalidQueryError(f"Unknown object type identifier: {expr.name}")

        elif isinstance(expr, exp.Var):
            if dialect == "snowflake":
                _type = SqlObjectType.STAGE
            else:
                _type = SqlObjectType.PREPARED_STATEMENT

        elif isinstance(expr, exp.Table):
            if isinstance(expr.this, exp.Var) and dialect == "snowflake":
                _type = SqlObjectType.STAGE
            else:
                _type = SqlObjectType.TABLE

        elif isinstance(expr, exp.Anonymous):
            if expr.this == "PROCEDURE":
                # CALL() statement
                _type = SqlObjectType.PROCEDURE
            else:
                # CTAS EXECUTE <statement(args)>
                _type = SqlObjectType.PREPARED_STATEMENT

        elif dialect == "postgres" and isinstance(expr, exp.Alias):
            if expr.this.name.upper() == "TABLE":
                # PREPARE X AS TABLE Y;
                _type = SqlObjectType.SELECT

        elif isinstance(expr, exp.Select):
            _type = SqlObjectType.SELECT

        elif isinstance(expr, exp.Values):
            _type = SqlObjectType.VALUES

        elif isinstance(expr, exp.OnConflict):
            # temporary; figure out how to handle this case
            _type = SqlObjectType.SET

        elif isinstance(expr, list) and isinstance(expr[0], exp.EQ):
            # UPDATE .. SET
            _type = SqlObjectType.SET

        elif isinstance(expr, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            _type = SqlObjectType.DML

        else:
            raise exception.InvalidQueryError(f"Unknown source/target object type in query: {type(expr)}")

        return _type

    def get_original_self(self) -> Query:
        return self.holder.original

    def get_transformed_self(self) -> Query | None:
        return self.holder.transformed

    def get_columns_from_target(self) -> t.List[exp.ColumnDef]:
        """
        Given a query, figure out its target object, including its columns.

        The structure is: INSERT INTO <target> .. <source>

        This is straightforward if 'source' isn't a JOIN: we just use the source object's columns.
        But if it is a JOIN, we use the selected columns rather than the source's columns.
        """
        if self.source_info is None:
            # TODO: temp. This occurs when CALL() invokes an SP with only a SELECT
            #  Remove this after CopyQuery refactor is complete
            return []

        source_expr = self.source_info.expression
        target_expr = self.target_info.expression
        target_type = self.target_info.type

        if SqlObjectType.type_has_no_column_defs(target_type):
            object_with_columns = source_expr
        elif target_type == SqlObjectType.TABLE:
            object_with_columns = target_expr
        else:
            raise exception.InvalidQueryError(f"Unhandled target object type: {target_type}")

        column_defs = self._get_column_defs(object_with_columns)
        if not column_defs:
            raise exception.InvalidQueryError(f"Could not find any columns for expression: {object_with_columns}")

        return column_defs

    def _get_column_defs(
        self,
        expr: SourceExprType | TargetExprType,
    ) -> t.List[exp.ColumnDef]:
        """
        Most of the time, the sources and target are tables.
        However, with COPY/UNLOAD, they can be files or streams.

        If the target is not a table and the source is a SELECT,
        there may be a JOIN with many tables as the source.
        """
        if not isinstance(expr, exp.Table):
            # Fall back to the source
            source = self.source_info.expression
            if isinstance(source, exp.Select):
                # TODO: this can't handle functions
                return [
                    exp.ColumnDef(this=exp.to_identifier(col.alias_or_name), kind=col.unalias().type)
                    for col in source.expressions
                ]

        table_query = self.object_mapping.get_table_or_stage(expr)
        if not table_query:
            return []

        return table_query.get_column_defs()

    def get_target_as_table(self) -> exp.Table:
        """
        For functions that only accept tables.
        """
        if not isinstance(self.target_info.expression, exp.Table):
            raise exception.InvalidQueryError(
                message=f"Expected the target object to be a table but it is a {type(self.target_info.type)}"
            )
        return self.target_info.expression

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        if self.parent_query:
            index = self.parent_query.get_statement_index()
            return index + ":" + str(self.statement_index)
        else:
            return str(self.statement_index)

    def get_ctes(self) -> t.List:
        return []

    def get_column_defs(self, include_system: bool = False) -> t.List[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> t.Dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns

    @property
    def id(self) -> str:
        return "query:" + util.short_sha256_hash(self.statement.sql() + ":" + str(self.statement_index))

    def add_child_query(self, child_query):
        child_query.parent_query = self
        self.child_queries.append(child_query)

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

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.statement_index,
        }
        return result
