from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass, replace
from functools import singledispatchmethod

from sqlglot import exp
from sqlglot.optimizer import Scope
from sqlglot.optimizer.scope import ScopeType

from sqlleaf import exception, util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    ColumnNode,
    FileColumnNode,
    FunctionNode,
    IntervalNode,
    JsonPathNode,
    LiteralNode,
    N,
    NullNode,
    ProgramNode,
    StageColumnNode,
    StarNode,
    StreamNode,
    TargetNodeType,
    UserDefinedFunctionNode,
    VariableNode,
    VarNode,
    WindowNode,
)
from sqlleaf.models.query import ProcedureQuery, Q, TableQuery
from sqlleaf.typing import SqlObjectType

logger = logging.getLogger("sqlleaf")


class SingleDispatchMethodLogger(singledispatchmethod):
    """
    Override the functools.singledispatchmethod class to print the methods that get called.
    Used for debugging purposes.
    """

    def __get__(self, obj: t.Any, cls: t.Any = None) -> t.Any:
        if obj is None:
            return self

        # Intercept execution and print the types
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            target_type = type(args[0])
            actual_func = self.dispatcher.dispatch(target_type)

            class_name, func_name = actual_func.__qualname__.rsplit(".", 1)
            logger.debug(f"Dispatching to: '{func_name}' ({class_name}) for expr: {type(args[0])}")

            result = actual_func(obj, *args, **kwargs)
            return result

        t.cast(t.Any, wrapper).register = self.register
        return wrapper


singledispatchmethodlogger = SingleDispatchMethodLogger


@dataclass(frozen=True)
class EdgeToCreate[N]:
    parent: N | None
    child: N | None


class BaseGenerator:
    # A registry to store subclasses
    _dialects = {}
    dialect = ""

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        raise exception.SqlLeafException(message=f"Unhandled expression type: {type(expr)}")

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        BaseGenerator._dialects[cls.dialect] = cls

    @classmethod
    def from_dialect(cls, class_name, *args, **kwargs):
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if not target_class:
            raise exception.SqlLeafException(message=f"Unknown dialect: {class_name}")
        return target_class()

    def do_grandparents(
        self,
        grandparents: t.List[exp.Expr],
        parent: t.Optional[N],
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ) -> t.Iterator[EdgeToCreate]:
        """
        Process a list of expressions of a parent expression.

        This is usually called after a parent->child edge being added to the graph
        with additional expressions to now process, i.e. [grandparents]->parent->child
        """
        if parent is None:
            raise exception.SqlLeafException(message="A parent cannot be None when processing grandparents.")
        if parent.kind in ["function", "udf"]:
            pos_ctx = replace(pos_ctx, function_depth=pos_ctx.function_depth + 1)

        for grand_expr in grandparents:
            gen_ctx = replace(gen_ctx, expr=grand_expr, child_node=parent)
            yield from self.process(gen_ctx.expr, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
            pos_ctx = replace(pos_ctx, function_arg_index=pos_ctx.function_arg_index + 1)

    @process.register
    def process_function(
        self, expr: exp.Func, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = FunctionNode(gen_ctx, pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

        grandparents = util.get_function_args(expr=expr)
        yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_placeholder(
        self, expr: exp.Placeholder, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        CREATE PROCEDURE proc(v_amount INT) AS
        SELECT v_amount     <-- placeholder
        """
        expr: exp.ColumnDef = expr.this
        gen_ctx = replace(gen_ctx, new_data_type=expr.kind)
        parent = VariableNode(gen_ctx, pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_array(
        self, expr: exp.Array, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in expr.expressions]
        values = "{" + ",".join(values) + "}"
        parent = LiteralNode(name=values, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_window(
        self, expr: exp.Window, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        parent = WindowNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register(exp.Literal)
    @process.register(exp.Boolean)
    def process_literal(
        self, expr: exp.Literal, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        select 'hello' as greeting
        """
        parent = LiteralNode(name=expr.sql(), gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_star(
        self, expr: exp.Star, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        select count(*) as cnt
        """
        parent = StarNode(gen_ctx, pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_null(
        self, expr: exp.Null, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = NullNode(gen_ctx, pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_neg(
        self, expr: exp.Neg, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT -10
        """
        parent = LiteralNode(name="-" + expr.name, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_variadic(
        self, expr: exp.Variadic, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        MLEAST(VARIADIC ARRAY[1, 2, 3])
        """
        gen_ctx = replace(gen_ctx, expr=expr.this)
        yield from self.process(expr.this, gen_ctx, pos_ctx)

    @process.register
    def process_anonymous(
        self, expr: exp.Anonymous, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        User-defined functions.

        SELECT my.func()
        """
        schema, function = util.get_udf_name(expr)

        # Process a UDF
        node_args = expr.expressions
        # node_args = list(expr.flatten())
        parent = UserDefinedFunctionNode(schema=schema, gen_ctx=gen_ctx, pos_ctx=pos_ctx)

        # TODO: pass the type to the above

        yield EdgeToCreate(parent, gen_ctx.child_node)

        grandparents = node_args
        yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_within_group(
        self, expr: exp.WithinGroup, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT MODE() WITHIN GROUP (ORDER BY name DESC) AS name
        """
        gen_ctx = replace(gen_ctx, expr=expr.this)
        yield from self.process(expr.this, gen_ctx, pos_ctx)

    @process.register
    def process_select(
        self, expr: exp.Select, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT (SELECT 1) AS name
                ^-------
        """
        # This is processed by the traversal into the subquery
        yield EdgeToCreate(None, None)

    @process.register
    def process_case(
        self, expr: exp.Case, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT CASE WHEN count(*) > 1 THEN 1 ELSE 0 END AS my_var
        """
        # If no default is specified, the default is NULL (via ANSI SQL) TODO: however in PL/pgsql it's an error instead
        default = expr.args.get("default", exp.Null())
        thens = [if_expr.args.get("true") or if_expr.args.get("false") for if_expr in expr.args.get("ifs", [])]
        grandparents = [default] + thens

        yield from self.do_grandparents(grandparents, gen_ctx.child_node, gen_ctx, pos_ctx)

    @process.register
    def process_binary(
        self, expr: exp.Binary, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT 1 + 2 AS age
        """
        if isinstance(expr, exp.Dot):
            # Process this as a UDF
            logger.debug("Found exp.Dot inside exp.Binary")
            gen_ctx = replace(gen_ctx, expr=expr.right)
            yield from self.process(expr.right, gen_ctx, pos_ctx)
        else:
            parent = FunctionNode(gen_ctx, pos_ctx)
            yield EdgeToCreate(parent, gen_ctx.child_node)

            grandparents = [expr.left, expr.right]
            yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_var(
        self, expr: exp.Var, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        A variable in a stored procedure or UDF, or the keyword 'DEFAULT'
        """
        parent = VarNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_column(
        self, expr: exp.Column, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        if is_node_a_placeholder(expr=expr, query=gen_ctx.query):
            # The actual placeholder is processed elsewhere
            return

        parent = ColumnNode(
            catalog=expr.catalog,
            schema=expr.db,
            table=expr.table,
            column=expr.name,
            gen_ctx=gen_ctx,
            pos_ctx=pos_ctx,
        )

        # Rename the column's table/schema/catalog to be fully qualified
        if gen_ctx.scope and isinstance(gen_ctx.scope, Scope):
            # Lateral queries are processed differently
            if gen_ctx.scope.scope_type == ScopeType.UDTF and isinstance(gen_ctx.scope.expression, exp.Lateral):
                source_table = dict(gen_ctx.scope.lateral_sources).get(expr.table)
            else:
                source_table = dict(gen_ctx.scope.references).get(expr.table)

            if source_table:
                if not isinstance(source_table, (exp.Table, exp.Values, exp.Subquery, exp.Select, exp.Lateral)):
                    raise exception.SqlLeafException(message=f"Unexpected source type: {type(source_table)}")

                if not isinstance(source_table, exp.Subquery):
                    parent.rename_table(source_table, gen_ctx.query.dialect)

        yield EdgeToCreate(parent, gen_ctx.child_node)

        if isinstance(parent.source_scope, exp.Table):
            # Traverse into the table (esp. needed by "ROWS FROM")
            ex = parent.source_scope
            gen_ctx = replace(gen_ctx, expr=ex, child_node=parent)
            yield from self.process(ex, gen_ctx, pos_ctx)

    @process.register(exp.JSONExtract)
    @process.register(exp.JSONBExtract)
    def process_json(
        self, expr: exp.JSONExtract, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = JsonPathNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx)

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        yield EdgeToCreate(parent, gen_ctx.child_node)

        gen_ctx = replace(gen_ctx, expr=source, child_node=parent)
        yield from self.process(source, gen_ctx, pos_ctx)

    @process.register
    def process_interval(
        self, expr: exp.Interval, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = IntervalNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register(exp.DataType)
    @process.register(exp.Identifier)
    @process.register(exp.ColumnDef)
    @process.register(exp.Table)
    def skip(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        logger.debug(f"Skipping expression: {type(expr)} {str(expr)}")
        yield EdgeToCreate(None, None)

    @process.register
    def process_values(
        self, expr: exp.Values, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT FROM (VALUES ())
        """
        selected_column: exp.Column = t.cast(exp.Column, gen_ctx.get_child_node().expr)

        # Select the correct values from the list according to the column's position in the alias
        if isinstance(expr.parent, exp.From):
            table_alias = expr.args["alias"]
            col_idx = [c.name for c in table_alias.columns].index(selected_column.name)
            value_exprs = [tup_expr.expressions[col_idx] for tup_expr in expr.expressions]

            grandparents = value_exprs
            parent = gen_ctx.child_node
            yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_bracket(
        self, expr: exp.Bracket, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Array/JSON subscripting: my_arr[0] or data['user']
        """
        inner = util.unwrap_expression(expr.this)
        gen_ctx = replace(gen_ctx, expr=inner)
        yield from self.process(inner, gen_ctx, pos_ctx)

    @process.register
    def process_subquery(
        self, expr: exp.Subquery, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT 1 + (SELECT 2)

        Given the above,
        1 is part of SELECT 1 ...
        2 is part of (SELECT 2 ...)
        (SELECT 2 ...) is part of SELECT 1 ...
        """
        if len(expr.selects) > 1 or isinstance(expr.this, exp.Union):
            raise exception.SqlLeafException("A subquery must return only one column")

        # Update the scope to be the subquery itself, as it is a subscope
        scope = t.cast(Scope, gen_ctx.scope)
        subquery_scope = [s for s in scope.subquery_scopes if s.expression == expr.this][0]

        height, width = gen_ctx.scope_positions.get_scope_for_expr(expr.this)
        child_ctx = replace(pos_ctx, query_depth=height, query_width=width)
        p_ctx = replace(gen_ctx, expr=expr.selects[0], scope=subquery_scope)
        return self.process(p_ctx.expr, gen_ctx=p_ctx, pos_ctx=child_ctx)

    def iter_child_nodes(
        self, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Generator[t.Tuple[TargetNodeType | None, ColumnNode | None]]:
        """
        Iterate over every column of a table that was either selected in a query or has a default expression.
        """

        # Both COPY and UNLOAD can have SELECTs as their sources, which have arbitrary
        # columns that vary in length due to their sourcing from any table.
        query = gen_ctx.query
        expr = query.get_target_expression()
        target_object = query.get_target_object()

        select_idx = 0

        # Iterate over every column and yield it if it is referenced in the query.
        for col_def in target_object.columns:
            selected_node = None
            default_node = None
            process_defaults = False
            gen_ctx = replace(gen_ctx, expr=col_def)
            pos_ctx = replace(pos_ctx, select_index=select_idx)

            # logger.debug(f"Iter nodes - found node: {target_object.type}")
            match target_object.type:
                case SqlObjectType.FILE:
                    file_format = getattr(query.get_original_self(), "file_format", "UNKNOWN")
                    child_node = FileColumnNode(
                        column=col_def.name,
                        file_format=file_format,
                        file_path=expr.name,
                        gen_ctx=gen_ctx,
                        pos_ctx=pos_ctx,
                    )

                case SqlObjectType.STAGE:
                    stage_query = query.object_mapping.get_table_or_stage(table=expr.this, raise_on_missing=False)
                    child_node = StageColumnNode(
                        column=col_def.name,
                        stage=expr.this,
                        gen_ctx=gen_ctx,
                        pos_ctx=pos_ctx,
                        path=stage_query.path,
                    )
                    process_defaults = False

                case SqlObjectType.TABLE:
                    child_node = ColumnNode(
                        catalog=expr.catalog,
                        schema=expr.db,
                        table=expr.name,
                        column=col_def.name,
                        gen_ctx=gen_ctx,
                        pos_ctx=pos_ctx,
                    )
                    process_defaults = True

                case SqlObjectType.STREAM:
                    # Use the ColumnDef as the expr so that correct columns
                    # are selected during walk()
                    child_node = StreamNode(
                        name=expr.name,
                        gen_ctx=gen_ctx,
                        pos_ctx=pos_ctx,
                    )

                case SqlObjectType.PROGRAM:
                    # Use the ColumnDef as the expr so that correct columns
                    # are selected during walk()
                    child_node = ProgramNode(
                        gen_ctx=gen_ctx,
                        pos_ctx=pos_ctx,
                    )

                case _:
                    raise exception.SqlLeafException(f"Unhandled case for type: {target_object.type}")


            if col_def.name in util.get_selected_column_names(query.statement) or isinstance(query, TableQuery):
                # Check if the column is selected.
                # A 'CREATE TABLE' has no SELECT, so include all columns if this case.
                selected_node = child_node

            if (
                process_defaults
                and isinstance(child_node, ColumnNode)
                and child_node.get_column_constraint_expression()
            ):
                default_node = child_node
                # TODO: unset all index positions, set 'default=true' as position

            if selected_node or default_node:
                yield selected_node, default_node

            if selected_node:
                select_idx += 1


def is_node_a_placeholder(expr: exp.Column, query: Q) -> bool:
    """
    Check if a Column is actually a Placeholder.

    For example, given
        CREATE PROCEDURE purchase(v_amount INT) AS
            SELECT v_amount as amount

    the 'v_amount' inside the SELECT will be a Column, but instead it should be a Placeholder.
    """
    if query.parent_query and isinstance(query.parent_query, ProcedureQuery):
        args = query.parent_query.args
        arg_names = [a["name"] for a in args]
        if expr.name in arg_names:
            logger.debug(f"Skipping Column {expr.name} as it is a Placeholder")
            return True
    return False
