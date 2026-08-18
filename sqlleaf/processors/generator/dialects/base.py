from __future__ import annotations

import logging
import typing as t
from dataclasses import dataclass
from functools import singledispatchmethod

from sqlglot import exp
from sqlglot.optimizer import Scope
from sqlglot.optimizer.scope import ScopeType

from sqlleaf import exception, util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    ColumnNode,
    DynamoDbNode,
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
    VarNode,
    WindowNode,
)
from sqlleaf.models.query import TableQuery
from sqlleaf.typing import SourceExprType, SqlObjectType, TargetExprType

logger = logging.getLogger("sqlleaf")


class SingleDispatchMethodLogger(singledispatchmethod):
    """
    Override the functools.singledispatchmethod class to print the methods that get called.
    Used for debugging purposes.
    """

    def __get__(self, obj: t.Any, cls: t.Any = None) -> t.Any:
        def wrapper(*args: t.Any, **kwargs: t.Any) -> t.Any:
            """
            Intercept execution and print the function calls.
            """
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

    def __init__(self):
        self.hooks = None

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        # See the functions below for correct examples.
        raise exception.SqlLeafException(message=f"Type is not yet registered with a method: {type(expr)}")

    def __init_subclass__(cls, **kwargs):
        """Automatically registers subclasses when they are defined."""
        super().__init_subclass__(**kwargs)
        BaseGenerator._dialects[cls.dialect] = cls

    @process.register(exp.DataType)
    @process.register(exp.Identifier)
    @process.register(exp.ColumnDef)
    @process.register(exp.Table)
    def skip(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        """
        This causes tree traversal to stop.
        """
        logger.debug(f"Skipping expression: {type(expr)} {str(expr)}")
        yield EdgeToCreate(None, None)

    @classmethod
    def from_dialect(cls, class_name) -> BaseGenerator:
        """Instantiates a class from the registry by name."""
        target_class = cls._dialects.get(class_name)
        if not target_class:
            return BaseGenerator()
        return target_class()

    def add_hooks(self, hooks: dict[N, t.Callable[[N], N | None]]) -> None:
        """
        Add user-defined hooks.
        """
        self.hooks = hooks

    def do_grandparents(
        self,
        grandparents: t.List[exp.Expr],
        parent: t.Optional[N],
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ) -> t.Iterator[EdgeToCreate]:
        """
        Process a list of grandparents, which are parents of parent expressions.

        This is called after a parent->child edge as been processed, and now we
        have additional expressions to now process, i.e. [grandparents]->parent->child
        """
        if parent is None:
            if gen_ctx.child_node is None:
                # Catches programming errors when adding new visitors
                raise exception.SqlLeafException(message="A parent cannot be None when processing grandparents.")

            # This may occur due to a user-provided hook function that turned the parent into None.
            # For example, perhaps we attempted to create the path [A -> B -> C] in the graph, but the hook prevented the
            # creation of B; thus we set A is the previous node and C as the next, resulting in the path [A -> C].
            parent = gen_ctx.child_node

        if parent.kind in ["function", "udf"]:
            pos_ctx = pos_ctx.replace(function_depth=pos_ctx.function_depth + 1)

        for grand_expr in grandparents:
            gen_ctx = gen_ctx.replace(expr=grand_expr, child_node=parent)
            yield from self.process(gen_ctx.expr, gen_ctx=gen_ctx, pos_ctx=pos_ctx)
            pos_ctx = pos_ctx.replace(function_arg_index=pos_ctx.function_arg_index + 1)

    def create_node(self, node: N) -> N | None:
        # Run against the hooks
        hook = self.hooks.get(type(node))
        if hook:
            logger.debug(f"Running hook '{hook.__name__}' on node type '{node.__class__.__name__}'")
            result = hook(node)
            return result
        return node

    @process.register(exp.AtTimeZone)
    @process.register(exp.Func)
    def process_function(
        self, expr: exp.Func, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = self.create_node(FunctionNode(gen_ctx, pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

        grandparents = util.get_function_args(expr=expr)
        yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_tuple(
        self, expr: exp.Tuple, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = gen_ctx.child_node
        grandparents = expr.expressions
        yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_array(
        self, expr: exp.Array, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT ARRAY[1,2,3]
        """
        values = [str(e) for e in expr.expressions]
        values = "{" + ",".join(values) + "}"
        parent = self.create_node(LiteralNode(name=values, gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_window(
        self, expr: exp.Window, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT ROW_NUMBER() OVER (ORDER BY name DESC) AS amount
        """
        parent = self.create_node(WindowNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register(exp.Literal)
    @process.register(exp.Boolean)
    def process_literal(
        self, expr: exp.Literal, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        select 'hello' as greeting
        """
        parent = self.create_node(LiteralNode(name=expr.sql(), gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_star(
        self, expr: exp.Star, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        select count(*) as cnt
        """
        parent = self.create_node(StarNode(gen_ctx, pos_ctx, name="*"))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_null(
        self, expr: exp.Null, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = self.create_node(NullNode(gen_ctx, pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_neg(
        self, expr: exp.Neg, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT -10
        """
        parent = self.create_node(LiteralNode(name="-" + expr.name, gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_anonymous(
        self, expr: exp.Anonymous, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Functions or user-defined functions, e.g. SELECT my.func()
        sqlglot recognises most functions as 'Anonymous', so we assume they're functions
        unless they're in the mapping.
        """
        schema, function = util.get_udf_name(expr)
        node_args = expr.expressions
        # node_args = list(expr.flatten())

        # A function has to be registered to be a UDF
        udf_query = gen_ctx.query.object_mapping.lookup_udf_call(expr)
        if udf_query:
            parent = self.create_node(UserDefinedFunctionNode(schema=schema, gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        else:
            parent = self.create_node(FunctionNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx))

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
        gen_ctx = gen_ctx.replace(expr=expr.this)
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
        if isinstance(expr, (exp.Dot, exp.Bracket)):
            # Field/Array access (a.b, a.b.c, a[0], a.b[0]) appears as a chain of exp.Dot/exp.Bracket nodes.
            # Walk back to the left-most object so lineage points at the real source column, not the final field token.
            logger.debug(f"Found {type(expr)} inside exp.Binary")
            base: exp.Expr = expr
            while isinstance(base, (exp.Dot, exp.Bracket)):
                base = base.this

            if isinstance(base, exp.Column):
                # If the base is a Column, run it through normal Column handling.
                logger.debug(f"Struct/Array access: processing base column {base.sql(dialect=self.dialect)}")
                gen_ctx = gen_ctx.replace(expr=base)
                yield from self.process(base, gen_ctx, pos_ctx)
            else:
                # If the base isn't a Column (e.g., a schema-qualified routine),
                # process only the right-hand side so that UDF/qualified-name dispatch still works
                gen_ctx = gen_ctx.replace(expr=expr.right if isinstance(expr, exp.Binary) else expr.this)
                yield from self.process(gen_ctx.expr, gen_ctx, pos_ctx)
        else:
            parent = self.create_node(FunctionNode(gen_ctx, pos_ctx))
            yield EdgeToCreate(parent, gen_ctx.child_node)

            grandparents = [expr.left, expr.right]
            yield from self.do_grandparents(grandparents, parent, gen_ctx, pos_ctx)

    @process.register
    def process_var(
        self, expr: exp.Var, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Var "QUARTER" in: "SELECT EXTRACT(QUARTER FROM <DATE>)"
        """
        parent = self.create_node(VarNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx, name=gen_ctx.expr.name))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_column(
        self, expr: exp.Column, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        source_table = None
        scope = gen_ctx.scope

        if scope and isinstance(scope, Scope):
            # Lateral queries are processed differently
            if scope.scope_type == ScopeType.UDTF and isinstance(scope.expression, exp.Lateral):
                source_table = dict(scope.lateral_sources).get(expr.table)

            elif scope.scope_type == ScopeType.SUBQUERY and isinstance(expr, exp.Column):
                source_table = dict(scope.references).get(expr.table)

                if not source_table:
                    # Check the scope's parents recursively for the actual source.
                    # This occurs in a subquery, e.g. SELECT ((SELECT r.name)) FROM fruit.raw r
                    parent = scope.parent
                    while parent:
                        source_table = dict(parent.references).get(expr.table)
                        if source_table or parent.scope_type != ScopeType.SUBQUERY:
                            break
                        parent = parent.parent
            else:
                source_table = dict(scope.references).get(expr.table)

            if source_table:
                if not isinstance(
                    source_table,
                    (exp.Table, exp.Subquery, exp.Select, exp.Union, exp.Lateral, exp.Unnest),
                ):
                    raise exception.SqlLeafException(message=f"Unexpected source type: {type(source_table)}")

        parent = ColumnNode(
            catalog=expr.catalog,
            schema=expr.db,
            table=expr.table,
            column=expr.name,
            gen_ctx=gen_ctx,
            pos_ctx=pos_ctx,
            source=source_table,
        )
        # Preserve the object as we need to access the object's properties below
        if maybe_parent := self.create_node(parent):
            yield EdgeToCreate(maybe_parent, gen_ctx.child_node)

        if isinstance(parent.source_scope, exp.Table):
            # Traverse into the table (esp. needed by "ROWS FROM")
            ex = parent.source_scope
            gen_ctx = gen_ctx.replace(expr=ex, child_node=parent)
            yield from self.process(ex, gen_ctx, pos_ctx)

    @process.register(exp.JSONExtractScalar)
    @process.register(exp.JSONExtract)
    @process.register(exp.JSONBExtract)
    def process_json(
        self, expr: exp.JSONExtract, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = self.create_node(JsonPathNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx))

        # Get the bottom expression to extract the JSON paths
        source = expr.this
        while isinstance(source, (exp.JSONExtract, exp.JSONExtractScalar)):
            source = source.this

        yield EdgeToCreate(parent, gen_ctx.child_node)

        gen_ctx = gen_ctx.replace(expr=source, child_node=parent)
        yield from self.process(source, gen_ctx, pos_ctx)

    @process.register
    def process_interval(
        self, expr: exp.Interval, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        parent = self.create_node(IntervalNode(gen_ctx=gen_ctx, pos_ctx=pos_ctx))
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_bracket(
        self, expr: exp.Bracket, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Array/JSON subscripting: my_arr[0] or data['user']
        """
        # Array access often behaves like a binary expression for lineage purposes (points to a base column)
        return self.process_binary(expr, gen_ctx, pos_ctx)

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
        logger.debug(
            f"process_subquery: scope.subquery_scopes={len(scope.subquery_scopes)}, expr.this={expr.this.sql()[:40]}"
        )
        subquery_scope = [s for s in scope.subquery_scopes if s.expression == expr.this][0]

        height, width = gen_ctx.scope_positions.get_position_for_expr(expr.this)
        child_ctx = pos_ctx.replace(query_depth=height, query_width=width)
        p_ctx = gen_ctx.replace(expr=expr.selects[0], scope=subquery_scope)
        yield from self.process(p_ctx.expr, gen_ctx=p_ctx, pos_ctx=child_ctx)

    def create_node_from_type(
        self,
        object_type: SqlObjectType,
        expression: TargetExprType | SourceExprType,
        column_name: str,
        gen_ctx: GeneratorContext,
        pos_ctx: PositionContext,
    ) -> TargetNodeType | None:
        """
        Create a node for a given object type.
        """
        match object_type:
            case SqlObjectType.FILE:
                file_format = gen_ctx.query.get_original_self().parameters.file_format
                new_node = FileColumnNode(
                    column=column_name,
                    file_format=file_format,
                    file_path=expression.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case SqlObjectType.STAGE:
                stage_expression = expression.this if isinstance(expression, exp.Table) else expression
                stage_query = gen_ctx.query.object_mapping.get_table_or_stage(table=expression, raise_on_missing=False)
                new_node = StageColumnNode(
                    column=column_name,
                    stage=stage_expression,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                    path=stage_query.path if stage_query else "",
                )

            case SqlObjectType.TABLE:
                new_node = ColumnNode(
                    catalog=expression.catalog if isinstance(expression, exp.Table) else "",
                    schema=expression.db if isinstance(expression, exp.Table) else "",
                    table=expression.name,
                    column=column_name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case SqlObjectType.STREAM:
                new_node = StreamNode(
                    name=expression.name,
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case SqlObjectType.PROGRAM:
                new_node = ProgramNode(
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                )

            case SqlObjectType.DYNAMODB:
                new_node = DynamoDbNode(
                    gen_ctx=gen_ctx,
                    pos_ctx=pos_ctx,
                    column=column_name,
                )

            case _:
                raise exception.SqlLeafException(f"Unhandled case for type: {object_type}")

        return self.create_node(new_node)

    def iter_child_nodes(
        self, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Generator[t.Tuple[TargetNodeType | None, ColumnNode | None]]:
        """
        Iterate over every column of a table that was either selected in a query or has a default expression.
        """

        # Both COPY and UNLOAD can have SELECTs as their sources, which have arbitrary
        # columns that vary in length due to their sourcing from any table.
        query = gen_ctx.query
        target_type = query.target_info.type
        expr = query.target_info.expression
        target_columns = query.get_columns_from_target()

        select_idx = 0

        # Iterate over every column and yield it if it is referenced in the query.
        for col_def in target_columns:
            selected_node = None
            default_node = None
            gen_ctx = gen_ctx.replace(expr=col_def)
            pos_ctx = pos_ctx.replace(select_index=select_idx)

            # logger.debug(f"Iter nodes - found node: {target_type}")
            child_node = self.create_node_from_type(
                object_type=target_type,
                expression=expr,
                column_name=col_def.name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            process_defaults = target_type == SqlObjectType.TABLE

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
