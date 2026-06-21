from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import exception, mappings, util
from sqlleaf.typing import E, SourceExprType, TargetExprType, SqlObjectType, SourceInfo, TargetInfo

logger = logging.getLogger("sqlleaf")


# TODO: put this in every Node class?
@dataclass(frozen=True)
class TargetObject:
    type: SqlObjectType
    # This is not the *actual* target: it's just what was used to derive the columns,
    # as the source will need to act as the target if the target isn't a table.
    object: TargetExprType | SourceExprType
    columns: t.List[exp.ColumnDef]


class Query:
    KIND: str = ""

    def __init__(
        self,
        dialect: str,
        statement: exp.Expr,
        statement_index: int,
        object_mapping: mappings.ObjectMapping,
        source_info: SourceInfo | None = None,
        target_info: TargetInfo | None = None,
        kind: str | None = None,
    ):
        self.kind = kind or self.KIND
        self.dialect = dialect
        self.object_mapping = object_mapping
        self.parent_query = None
        self.child_queries = []
        self.column_defs: t.List[exp.ColumnDef] = []
        self.property = ""

        # Remove comments at initialization
        for expr in statement.walk():
            expr.pop_comments()

        self.statement_original: exp.Expr | None = None
        self.statement_transformed: exp.Expr | None = None
        self.statement_substituted: exp.Expr | None = None

        self.statement_index = statement_index  # The position of this query within a list of queries
        self.set_original_statement(statement)

        if source_info:
            self.source_info = source_info
        if target_info:
            self.target_info = target_info

        logger.debug(f"Created Query: {self.__class__}")

    def _determine_expression_type(self, expr: exp.Expr | t.List[exp.Expr], dialect: str) -> SqlObjectType:
        if isinstance(expr, exp.Literal):
            _type = SqlObjectType.FILE

        elif isinstance(expr, exp.Identifier):

            if expr.name in ["stdin", "stdout"]:
                _type = SqlObjectType.STREAM
            elif expr.name in ["program"]:
                _type = SqlObjectType.PROGRAM
            else:
                raise exception.SqlLeafException(f"Unknown object type identifier: {expr.name}")

        elif isinstance(expr, exp.Var) and dialect == "snowflake":
            _type = SqlObjectType.STAGE

        elif isinstance(expr, exp.Table):
            if isinstance(expr.this, exp.Var) and dialect == "snowflake":
                _type = SqlObjectType.STAGE
            else:
                _type = SqlObjectType.TABLE

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

        else:
            raise exception.SqlLeafException(f"Unknown source/target object type in query: {type(expr)}")

        return _type

    def qualify_and_annotate(self):
        from sqlglot.optimizer.qualify import qualify
        from sqlglot.optimizer.annotate_types import annotate_types
        qualify(
            self.source_info.expression,
            schema=self.object_mapping,
            expand_stars=True,
            expand_alias_refs=False,
            qualify_columns=True,
            infer_schema=False,
            dialect=self.dialect,
            isolate_tables=False,
            validate_qualify_columns=False,
            quote_identifiers=False,
        )

        annotate_types(self.source_info.expression, dialect=self.dialect, schema=self.object_mapping)

    @property
    def statement(self) -> E:
        return self._statement

    def get_target_object(self) -> TargetObject:
        """
        Given a query, figure out its target object, including its columns.

        This is straightforward if source isn't a JOIN: we just use the source object's columns.
        But if it is a JOIN, we use the selected columns rather than the source's columns.
        """
        source_expr = self.source_info.expression
        target_expr = self.target_info.expression
        target_type = self.target_info.type

        if target_type in [SqlObjectType.FILE, SqlObjectType.PROGRAM, SqlObjectType.STAGE,  SqlObjectType.STREAM]:
            object_with_columns = source_expr
        elif target_type == SqlObjectType.TABLE:
            object_with_columns = target_expr
        else:
            raise exception.SqlLeafException(f"Unhandled target object type: {target_type}")

        column_defs = self._get_column_defs(object_with_columns)
        return TargetObject(
            type=target_type,
            object=object_with_columns,
            columns=column_defs,
        )

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

    def get_target_expression(self) -> TargetExprType:
        return self.target_info.expression

    def get_target_as_table(self) -> exp.Table:
        """
        For functions that only accept tables.
        """
        if not isinstance(self.get_target_expression(), exp.Table):
            raise exception.SqlLeafException(
                message=f"Expected the target object to be a table but it is a {type(self.target_info.type)}"
            )
        return self.get_target_expression()

    def get_statement_index(self) -> str:
        """
        Get the statement index for this query (including its parents).
        """
        if self.parent_query:
            index = self.parent_query.get_statement_index()
            return index + ":" + str(self.statement_index)
        else:
            return str(self.statement_index)

    def set_transformed_statement(self, statement: exp.Expr) -> None:
        self.statement_transformed = statement
        self._statement = statement

    def set_original_statement(self, statement: exp.Expr) -> None:
        self.statement_original = statement
        self._statement = statement

    def set_substituted_statement(self, statement: exp.Expr) -> None:
        self.statement_substituted = statement

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
        return "query:" + util.short_sha256_hash(self.statement_original.sql() + ":" + str(self.statement_index))

    def set_to_original(self):
        """
        Convert the Query back to its original statement.

        This is needed for CTAS/View queries after they transform into Inserts.
        This is the inverse of functions like set_as_insert()
        """
        self.set_original_statement(statement=self.statement_original)

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

    def get_selected_column_names(self) -> t.List[str]:
        if isinstance(self.statement.expression, exp.Values):
            return [s.name for s in self.statement.this.expressions]
        return [s.alias_or_name for s in self.statement.selects]

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.statement_index,
        }
        return result


# why can't I start building logic for every Query type
# that extracts the Source, Target and the columns?
# There's so much code that is trying to calculate the right
# values from the source/target, but there are too many exceptions
# related to INSERT, COPY, etc
