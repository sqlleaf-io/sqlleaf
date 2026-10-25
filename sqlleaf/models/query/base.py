from __future__ import annotations

import dataclasses
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
        target_info: TargetInfo | None,
        skip_type_annotation: bool = False,
    ):
        self.kind = self.KIND
        self.dialect = dialect
        self.object_mapping = object_mapping
        self.child_queries = []
        self.column_defs: list[exp.ColumnDef] = []
        self.property = ""

        # Remove comments at initialization
        for expr in statement.walk():
            expr.pop_comments()

        if skip_type_annotation:
            # Prevent overwriting the types with UNKNOWN if they've already been annotated
            annotate_types(statement, dialect=dialect, schema=object_mapping)

        self.statement: exp.Expr = statement
        self.statement_index = statement_index  # The position of this query within a list of queries

        self.source_info, self.target_info = self._resolve_source_and_target_info(source_info, target_info)

        logger.debug(
            f"Created new query. Query => {self.__class__.__name__} | SourceType => {self.source_info and self.source_info.type.name} | TargetType => {self.target_info and self.target_info.type.name}"
        )

    def set_holder(self, holder: QueryHolder) -> None:
        self.holder = holder

    def _determine_expression_type(self, expr: exp.Expr | list[exp.Expr], dialect: str) -> SqlObjectType:
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

        elif isinstance(expr, exp.Union):
            _type = SqlObjectType.UNION

        else:
            raise exception.InvalidQueryError(f"Unknown source/target object type in query: {type(expr)}")

        return _type

    def refresh_source_and_target_info(self) -> None:
        """
        Resolve the expressions again, once the tables they depend on have been registered in the object mapping.
        """
        self.source_info, self.target_info = self._resolve_source_and_target_info(self.source_info, self.target_info)

    def _resolve_source_and_target_info(
        self, source_info: SourceInfo | None, target_info: TargetInfo | None
    ) -> tuple[SourceInfo | None, TargetInfo | None]:
        """
        Compute the source and target expressions for a query.
        """
        source_exprs: list[exp.Expr] = []
        target_exprs: list[exp.Expr] = []

        if source_info and source_info.type == SqlObjectType.SET and isinstance(source_info.expression, list):
            # UPDATE .. SET a = 1: the right-hand side is the source, the left-hand column is the target
            source_exprs = [eq.expression for eq in source_info.expression]
            target_exprs = [eq.this for eq in source_info.expression]
        elif source_info and source_info.type == SqlObjectType.SELECT and isinstance(source_info.expression, exp.Query):
            source_exprs = list(source_info.expression.selects)
        elif source_info and isinstance(source_info.expression, (exp.Values, exp.Tuple)):
            source_exprs = list(source_info.expression.expressions)

        # SET with a non-list expression (ON CONFLICT) and UPDATE's SET list are handled above
        if source_info and target_info and source_info.type != SqlObjectType.SET:
            if target_info.type == SqlObjectType.TABLE:
                target_exprs = self._get_table_column_copies(target_info.expression)
            if source_info.type == SqlObjectType.TABLE:
                source_exprs = self._get_table_column_copies(source_info.expression)

            # A side without columns of its own takes them from the table on the other side
            if SqlObjectType.type_has_no_column_defs(source_info.type) and target_info.type == SqlObjectType.TABLE:
                source_exprs = [col.copy() for col in target_exprs]

            if SqlObjectType.type_has_no_column_defs(target_info.type):
                if source_info.type == SqlObjectType.TABLE:
                    target_exprs = [col.copy() for col in source_exprs]
                elif source_info.type == SqlObjectType.SELECT:
                    # COPY (SELECT ..) TO file: the file's columns are the projections
                    target_exprs = [
                        exp.ColumnDef(this=exp.to_identifier(col.alias_or_name), kind=col.unalias().type)
                        for col in source_exprs
                    ]

        source_info = dataclasses.replace(source_info, expressions=source_exprs) if source_info else None
        target_info = dataclasses.replace(target_info, expressions=target_exprs) if target_info else None
        return source_info, target_info

    def _get_table_column_copies(self, table: exp.Table | exp.Var | exp.Schema) -> list[exp.Expr]:
        """
        Return copies of a table's columns, so that the object mapping is never aliased.
        """
        if isinstance(table, exp.Schema):
            # INSERT INTO <table>(<columns>)
            table = table.this
        table_query = self.object_mapping.get_table_or_stage(table, raise_on_missing=False)
        if not table_query:
            return []
        return [col.copy() for col in table_query.get_column_defs()]

    def get_sources(self) -> list[exp.Expr]:
        """
        Return the source expressions, fixed at instantiation.
        """
        return self.source_info.expressions if self.source_info else []

    def get_targets(self) -> list[exp.Expr]:
        """
        Return the target expressions, fixed at instantiation.
        """
        return self.target_info.expressions if self.target_info else []

    def get_original_self(self) -> Query:
        return self.holder.original

    def get_transformed_self(self) -> Query | None:
        return self.holder.transformed

    def get_target_as_table(self) -> exp.Table:
        """
        For functions that only accept tables.
        """
        if not isinstance(self.target_info.expression, exp.Table):
            raise exception.InvalidQueryError(
                message=f"Expected the target object to be a table but it is a {repr(self.target_info.type)}"
            )
        return self.target_info.expression

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        return str(self.statement_index)

    def get_ctes(self) -> list:
        return []

    def get_column_defs(self, include_system: bool = False) -> list[exp.ColumnDef]:
        return self.column_defs

    def get_column_names_with_types(self, include_system: bool = False) -> dict[str, str]:
        """
        Used by sqlglot's MappingSchema
        """
        columns = {col.name: str(col.kind) for col in self.get_column_defs(include_system=include_system)}
        return columns

    @property
    def id(self) -> str:
        return "query:" + util.short_sha256_hash(self.statement.sql(dialect=self.dialect) + ":" + str(self.statement_index))

    def get_all_queries(self, types: tuple | None = None):
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
            "statement_index": self.statement_index,
        }
        return result
