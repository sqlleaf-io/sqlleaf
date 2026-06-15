from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass

from sqlglot import exp

from sqlleaf import exception, mappings, util
from sqlleaf.typing import E, SourceExprType, TargetExprType, TargetObjectType

logger = logging.getLogger("sqlleaf")


# TODO: put this in every Node class?
@dataclass(frozen=True)
class TargetObject:
    type: TargetObjectType
    # This is not the *actual* target: it's just what was used to derive the columns,
    # as the source will need to act as the target if the target isn't a table.
    object: TargetExprType | SourceExprType
    columns: t.List[exp.ColumnDef]


class Query:
    def __init__(
        self,
        kind: str,
        dialect: str,
        statement: exp.Expr,
        target_object: TargetExprType,
        statement_index: int,
        object_mapping: mappings.ObjectMapping,
    ):
        self.kind = kind
        self.dialect = dialect
        self.target_object = target_object  # The target table
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

        self.source: SourceExprType

        logger.debug(f"Created Query: {self.__class__}")

    @property
    def statement(self) -> E:
        return self._statement

    def get_target_object(self) -> TargetObject:
        """
        Given a query, figure out its target object, including its columns.

        This is straightforward if source isn't a JOIN: we just use the source object's columns.
        But if it is a JOIN, we use the selected columns rather than the source's columns.
        """
        expr = self.get_target()

        if isinstance(expr, exp.Literal):
            # Use the parent table's columns as the child columns
            # Assumes this is a COPY | UNLOAD
            target_type = TargetObjectType.FILE
            object_with_columns = self.get_source()

        elif isinstance(expr, exp.Identifier):
            object_with_columns = self.get_source()

            if expr.name in ["stdin", "stdout"]:
                target_type = TargetObjectType.STREAM
            elif expr.name in ["program"]:
                target_type = TargetObjectType.PROGRAM
            else:
                raise exception.SqlLeafException(f"Unknown child column name in COPY: {expr.name}")

        elif isinstance(expr, exp.Table) and self.dialect == "snowflake":
            if isinstance(expr.this, exp.Var):
                target_type = TargetObjectType.STAGE
                # TODO: this assumes the source is a table!
                object_with_columns = self.get_source()
            else:
                target_type = TargetObjectType.TABLE
                object_with_columns = self.get_target()

        elif isinstance(expr, exp.Table):
            target_type = TargetObjectType.TABLE
            object_with_columns = self.get_target_as_table()

        else:
            raise exception.SqlLeafException(f"Unknown child column type in COPY: {expr}")

        column_defs = self._get_column_defs(object_with_columns)
        return TargetObject(
            type=target_type,
            object=object_with_columns,
            columns=column_defs,
        )

    def _get_column_defs(
        self,
        target: SourceExprType | TargetExprType,
    ) -> t.List[exp.ColumnDef]:
        """
        Most of the time, the sources and target are tables.
        However, with COPY/UNLOAD, they can be files or streams.

        If the target is not a table and the source is a SELECT,
        there may be a JOIN with many tables as the source.
        """
        if not isinstance(target, exp.Table):
            return []

        table_query = self.object_mapping.get_table_or_stage(target)
        if not table_query:
            return []

        return table_query.get_column_defs()

    def get_source(self) -> SourceExprType:
        return self.source

    def get_target(self) -> TargetExprType:
        return self.target_object

    def get_target_as_table(self) -> exp.Table:
        """
        For functions that only accept tables.
        """
        if not isinstance(self.target_object, exp.Table):
            raise exception.SqlLeafException(
                message=f"Expected the target object to be a table but it is a {type(self.target)}"
            )
        return self.target_object

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
        self.set_original_statement(statement=self.statement_original)

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
        return [s.alias_or_name for s in self.statement.selects]
        return self.statement.named_selects

    def to_dict(self):
        result = {
            "id": self.id,
            "kind": self.kind,
            "index": self.statement_index,
        }
        return result
