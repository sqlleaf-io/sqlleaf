from __future__ import annotations

import logging
import typing as t
from enum import StrEnum, auto

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, ScopeType

from sqlleaf import exception, util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.query_types import Q
from sqlleaf.typing import TableOrScopeType

logger = logging.getLogger("sqlleaf")


def _function_name(expr: exp.Expr, dialect: str) -> str:
    """
    Remove everything from the first '(' to the last ')' from a string.
    We use this method because exp.Func.sql_name() includes the function's context in its name.
    """
    try:
        # Get the name without its parameters
        name = expr.__class__().sql(dialect=dialect)
    except TypeError:
        # Some classes can't be converted to SQL using this method (e.g. CONCAT() in Postgres)
        name = expr.__class__().sql()

    first_bracket = name.find("(")
    if first_bracket == -1:
        return name

    last_bracket = name.rfind(")")
    if last_bracket == -1:
        return name

    return name[:first_bracket] + name[last_bracket + 1 :]


class TableType(StrEnum):
    TABLE = auto()
    VIEW = auto()
    CTE = auto()
    DERIVED_TABLE = auto()
    STAGE = auto()
    FILE = auto()


class TableSubtype(StrEnum):
    RECURSIVE = auto()
    TEMPORARY = auto()
    EXTERNAL = auto()
    MATERIALIZED = auto()


class NodeAttributes:
    def __init__(
        self,
        expr: exp.Expr,
        data_type: exp.DataType | None,
        pos_ctx: PositionContext,
        name: str,
        kind: str = "",
        with_positions: bool = False,
    ):
        self.expr = expr
        self.data_type = str(data_type) if data_type else ""
        self._data_type = data_type
        self.name = name
        self.kind = kind
        self.ctx = pos_ctx
        self.with_positions = with_positions

    # Allows the class to be used a networkx node
    def __hash__(self) -> int:
        return hash(self.full_name)

    def get_data_type(self) -> exp.DataType:
        assert self._data_type is not None
        return self._data_type

    def wrap(self, name: str, with_positions: bool = False) -> str:
        if with_positions:
            pos = self.ctx.as_str()
            name = f"{name} {pos}"
        return f"{self.kind}[{name}]"

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def friendly_fields(self) -> dict[str, str]:
        return {}

    def get_name(self) -> str:
        return self.name

    def _build_name(self, fields_dict: dict[str, str], with_positions: bool = False) -> str:
        """Build a formatted name with fields."""
        fields = " ".join([f"{k}={v}" for k, v in fields_dict.items() if v])
        name = f"{self.get_name()} {fields}" if fields else self.get_name()
        return self.wrap(name, with_positions=with_positions)

    @property
    def full_name(self) -> str:
        return self._build_name(self.fields(), with_positions=self.with_positions)

    @property
    def friendly_name(self) -> str:
        return self._build_name(self.friendly_fields())

    @property
    def id(self) -> str:
        # TODO: add correct fields
        fields_dict = self.fields()
        fields = [
            self.name,
            util.type_name(self.expr),
        ]
        # Add values from fields_dict to the hash
        for k, v in sorted(fields_dict.items()):
            fields.append(f"{k}={v}")

        name = "node:" + util.short_sha256_hash(":".join(fields))
        return name

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "name": self.name,
            "data_type": self.data_type,
            "kind": self.kind,
        }


class LiteralNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="literal",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        return self.name.replace("'", '"')


class ColumnNode(NodeAttributes):
    def __init__(
        self,
        catalog: str,
        schema: str,
        table: str,
        column: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = t.cast(exp.ColumnDef, gen_ctx.expr)

        super().__init__(
            kind="column",
            name=column,
            data_type=gen_ctx.data_type,
            expr=expr,
            pos_ctx=pos_ctx,
        )
        self.catalog = catalog
        self.schema = schema
        self.table = table
        self.member = ""

        self.parent_kind: str = ""
        self.parent_subkind: str = ""
        self.source_scope: TableOrScopeType | None = None
        self.has_child_scope: bool = (
            False  # Whether the query's source is inside an inner scope that still need to be resolved
        )

        self.set_table_properties(catalog, schema, table, gen_ctx)

        # TODO: new algorithm
        # if table_type == "cte":
        #     self.member = gen_ctx.node.recursive_cte_member_kind

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "catalog": self.catalog,
                "schema": self.schema,
                "table": self.table,
            }
        )
        return d

    def rename_table(self, source: exp.Table | exp.Values, dialect: str) -> None:
        """
        Change the column's source table to be its fully qualified name, not its alias,
        so that the ColumnNode is provided complete information.
        """
        column = t.cast(exp.Column, self.expr)
        _c = column.copy()

        if isinstance(source, exp.Table):
            if source.catalog:
                column.set("catalog", exp.to_identifier(source.catalog))
            if source.db:
                column.set("db", exp.to_identifier(source.db))
            if source.name:
                if dialect == "snowflake":
                    if source.this.args.get("quoted", False):  # exp.Identifier
                        column.set("table", exp.to_identifier(source.name))
                else:
                    column.set("table", exp.to_identifier(source.name))
            if _c != column:
                logger.debug(f"Renamed node {_c.sql()} to {column.sql()}")

            self.expr = column
            self.catalog = column.catalog
            self.schema = column.db
            self.table = column.table

    def set_table_properties(self, catalog: str, schema: str, table: str, gen_ctx: GeneratorContext) -> None:
        """
        Figure out the table's type (view/table) by inspecting the original query in the mapping.
        """
        tokens = []
        scope = gen_ctx.scope
        if isinstance(scope, Scope):
            source = scope.sources.get(table)
            if not source:
                # Nested 'rows_from' queries have their aliases in 'references'
                self.source_scope = dict(scope.references).get(table)  # tyy: ignore[invalid-assignment]
                self.parent_kind = TableType.DERIVED_TABLE
                return

            self.source_scope: TableOrScopeType = source

            if isinstance(source, exp.Table):
                tokens = [str(s) for s in source.parts]
                if "rows_from" in source.args:
                    self.parent_kind = TableType.DERIVED_TABLE
                    return

            elif isinstance(source, Scope):
                self.has_child_scope = True

                if isinstance(source.expression, exp.Values):
                    self.parent_kind = TableType.DERIVED_TABLE
                    return
                elif source.scope_type == ScopeType.CTE:
                    selected_table, _ = scope.selected_sources.get(table, (None, None))
                    if not selected_table:
                        message = f"Table '{table}' is referenced but there is no FROM containing it."
                        raise exception.SqlLeafException(message=message)

                    logger.debug("Set node to be a CTE.")
                    self.parent_kind = TableType.CTE

                    # Check if the CTE is a subtype
                    if source.parent:
                        for cte in source.parent.ctes:
                            if cte.alias_or_name == selected_table.name:
                                if cte.args["materialized"]:
                                    self.parent_subkind = TableSubtype.MATERIALIZED
                                else:
                                    with_ = cte.parent
                                    if isinstance(with_, exp.With) and with_.recursive:
                                        # TODO: requires new algorithm
                                        logger.debug("Set node to be a recursive CTE.")
                                        self.parent_subkind = TableSubtype.RECURSIVE
                                break
                    return

                elif source.scope_type == ScopeType.DERIVED_TABLE:
                    # PIVOT
                    self.parent_kind = TableType.DERIVED_TABLE
                    return

        else:
            tokens = [catalog, schema, table]

        # Get the table type from the mapping
        name = ".".join([tok for tok in tokens if tok])
        tab = exp.to_table(name, dialect=gen_ctx.query.dialect)
        query = gen_ctx.object_mapping.get_table_or_stage(table=tab, raise_on_missing=False)

        if not query or query.kind == "ctas":
            self.parent_kind = TableType.TABLE
        else:
            self.parent_kind = TableType(query.kind)

        if query.property:
            self.parent_subkind = TableSubtype(query.property)

    def get_column_constraint_expression(self) -> exp.ColumnConstraintKind | None:
        """
        Get the DEFAULT or GENERATED expression for this column, if it exists.
        There is only one, but this
        """
        types = (exp.DefaultColumnConstraint, exp.ComputedColumnConstraint)
        expr = t.cast(exp.ColumnDef, self.expr)
        constraints = [
            c.kind for c in expr.constraints if isinstance(c, exp.ColumnConstraint) and isinstance(c.kind, types)
        ]
        return t.cast(exp.ColumnConstraintKind, constraints[0]) if constraints else None

    def get_name(self):
        tokens = [self.catalog, self.schema, self.table, self.name]
        return ".".join([tok for tok in tokens if tok])

    @property
    def full_name(self):
        fields_dict = self.fields()
        fields = " ".join([f"{k}={v}" for k, v in fields_dict.items() if v])
        return self.wrap(fields, with_positions=self.with_positions)

    def as_table(self) -> exp.Table:
        return exp.table_(catalog=self.catalog, db=self.schema, table=self.table)

    def fields(self) -> dict[str, str]:
        f = {
            "name": self.name,
            "table": self.table,
            "schema": self.schema,
            "type": self.data_type,
            "kind": self.parent_kind,
        }

        if self.parent_subkind:
            f["subkind"] = self.parent_subkind

        if self.parent_kind == TableType.CTE and self.parent_subkind == TableSubtype.RECURSIVE:
            f["member"] = self.member

        if self.parent_kind == TableType.CTE:
            f["statement"] = str(self.ctx.statement_index)

        return f


class FileColumnNode(NodeAttributes):
    def __init__(
        self,
        column: str,
        file_format: str,
        file_path: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = t.cast(exp.ColumnDef, gen_ctx.expr)

        super().__init__(
            kind="column",
            name=column,
            data_type=gen_ctx.data_type,
            expr=expr,
            pos_ctx=pos_ctx,
        )
        self.file_format = file_format
        self.file_path = file_path

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "format": self.file_format,
                "path": self.file_path,
            }
        )
        return d

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "kind": "file",
            "format": self.file_format,
            "path": self.file_path,
        }

    def friendly_fields(self) -> dict[str, str]:
        return {"path": self.file_path}


class StageColumnNode(NodeAttributes):
    def __init__(
        self,
        column: str,
        stage: exp.Var,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        super().__init__(
            kind="column",
            name=column,
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            pos_ctx=pos_ctx,
        )
        self.stage = stage.name.removeprefix("@").replace('"', "")

    def to_dict(self):
        d = super().to_dict()
        d.update(
            {
                "stage": self.stage,
            }
        )
        return d

    def fields(self) -> dict[str, str]:
        return {
            "type": self.data_type,
            "kind": "stage",
            "stage": self.stage,
        }

    def friendly_fields(self) -> dict[str, str]:
        return {"stage": self.stage}


class FunctionNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(t.Union[exp.Binary, exp.Func], gen_ctx.expr)

        if isinstance(expr, exp.Binary):
            name = expr.key
        else:
            name = _function_name(expr, gen_ctx.query.dialect)

        super().__init__(
            kind="function",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}

    def get_name(self) -> str:
        return f"{self.name}".upper()


class UserDefinedFunctionNode(NodeAttributes):
    def __init__(
        self,
        schema: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ):
        expr = gen_ctx.expr

        super().__init__(
            kind="udf",
            data_type=gen_ctx.data_type,
            expr=expr,
            name=expr.this,
            pos_ctx=pos_ctx,
            with_positions=True,
        )
        self.schema = schema

    def get_name(self) -> str:
        tokens = [self.schema, self.name]
        return ".".join([tok for tok in tokens if tok]).upper()

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}


class JsonPathNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.JSONExtract, gen_ctx.expr)

        self.selectors = self.json_selectors(expr)
        self.selector = "".join([str(s) for s in self.selectors])
        self.selector_depth = len(self.selectors)

        super().__init__(
            kind="jsonpath",
            data_type=gen_ctx.data_type,
            expr=expr,
            name=self.selector,
            pos_ctx=pos_ctx,
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

    def fields(self) -> dict[str, str]:
        return {"depth": str(self.selector_depth)}

    def friendly_fields(self) -> dict[str, str]:
        return {}


class VariableNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="variable",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name="todo",
            pos_ctx=pos_ctx,
        )


class StarNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="star",
            data_type=exp.DataType.build("UNKNOWN"),
            expr=gen_ctx.expr,
            name="*",
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {}


class VarNode(NodeAttributes):
    def __init__(self, gen_ctx, pos_ctx: PositionContext):
        super().__init__(
            kind="var",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name=gen_ctx.expr.name,
            pos_ctx=pos_ctx,
        )


class NullNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="null",
            data_type=exp.DataType.build("NULL"),
            expr=gen_ctx.expr,
            name="null",
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": exp.DataType.build("NULL")}

    def get_name(self) -> str:
        return "NULL"


class SequenceNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext, subkind: str = ""):
        super().__init__(
            kind="sequence",
            data_type=exp.DataType.build("INT"),
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )
        self.subkind = subkind

    def fields(self) -> dict[str, str]:
        f = {"type": self.data_type}
        if self.subkind:
            f["kind"] = self.subkind
        return f


class WindowNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Window, gen_ctx.expr.this)

        super().__init__(
            kind="window",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=_function_name(expr, gen_ctx.query.dialect),
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}


class IntervalNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Interval, gen_ctx.expr)
        name = f'"{str(expr.this.name)} {str(expr.unit)}"'
        super().__init__(
            kind="interval",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
            with_positions=True,
        )

    def fields(self) -> dict[str, str]:
        return {"type": self.data_type}


class _PivotNode(NodeAttributes):
    def __init__(self, kind: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Column, gen_ctx.expr)
        super().__init__(
            kind=kind,
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=expr.name,
            pos_ctx=pos_ctx,
        )
        self.source: str = ""
        self.target: str = ""

    def set(self, source: str, target: str):
        self.source = source
        self.target = target

    def fields(self) -> dict[str, str]:
        f = {}
        # Keep empty strings as values to match expected test output
        f["source"] = self.source
        f["target"] = self.target
        f["statement"] = str(self.ctx.statement_index)
        return f

    def get_name(self) -> str:
        return ""

    @property
    def full_name(self):
        fields = " ".join([f"{k}={v}" for k, v in self.fields().items()])
        return self.wrap(fields)


class PivotNode(_PivotNode):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__("pivot", gen_ctx, pos_ctx)


class UnpivotNode(_PivotNode):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__("unpivot", gen_ctx, pos_ctx)


class StreamNode(NodeAttributes):
    def __init__(self, name: str, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        super().__init__(
            kind="stream",
            data_type=gen_ctx.data_type,
            expr=gen_ctx.expr,
            name=name,
            pos_ctx=pos_ctx,
        )

    def fields(self) -> dict[str, str]:
        return {}

    def get_name(self) -> str:
        return self.name


class ProgramNode(NodeAttributes):
    def __init__(self, gen_ctx: GeneratorContext, pos_ctx: PositionContext):
        expr = t.cast(exp.Copy, gen_ctx.query.statement_original)

        program = expr.args["params"][0].sql()
        name, args = (program + " ").split(" ", maxsplit=1)
        super().__init__(
            kind="program", data_type=exp.DataType.build("UNKNOWN"), expr=gen_ctx.expr, pos_ctx=pos_ctx, name=name
        )
        self.program_args = args.strip()

    def fields(self) -> dict[str, str]:
        return {"args": f"'{self.program_args}'"}


class EdgeAttributes:
    def __init__(
        self,
        parent: NodeAttributes,
        child: NodeAttributes,
        query: Q,
        select_idx: int,
        path_idx: int,
    ):
        self.parent = parent
        self.child = child
        self.query = query

        # The position of this column inside a set of selected columns (e.g. SELECT 'a', 'b', 'c')
        self.select_idx = select_idx

        # The position of this edge inside a set of identical edges (e.g. two edges between nodes A->B).
        # This can occur if the same query is used across multiple files.
        # <TODO: can I rely on the query hash instead?>
        self.path_idx = path_idx

        self.path_id: str | None = None
        self.path_hop: int | None = None

    @property
    def id(self):
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
        return "edge:" + util.short_sha256_hash(edge_id)

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
            "query": {"id": self.query.id},
        }
        return result


class GraphAttributes:
    def __init__(self):
        self.queries: t.List[Q] = []

    def add_query(self, query: Q):
        self.queries.append(query)


N = t.TypeVar("N", bound=NodeAttributes)
TargetNodeType = ColumnNode | FileColumnNode | StageColumnNode | StreamNode | ProgramNode
