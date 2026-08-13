from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import exception, util
from sqlleaf.models.context import GeneratorContext, PositionContext
from sqlleaf.models.node import (
    ColumnNode,
    SequenceNode,
)
from sqlleaf.processors.generator.dialects.base import BaseGenerator, EdgeToCreate, singledispatchmethodlogger
from sqlleaf.typing import SourceInfo, SqlObjectType

logger = logging.getLogger("sqlleaf")


class PostgresGenerator(BaseGenerator):
    dialect = "postgres"

    @singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_table(
        self, expr: exp.Table, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Process a table or a table function.
        This is a bit awkward as we have the sequence: Table -> ColumnDef -> Table
        for table functions.
        """
        if "rows_from" in expr.args:
            yield from self._process_rows_from(expr, gen_ctx, pos_ctx)
        elif isinstance(expr.this, exp.Anonymous):
            yield from super().process(expr.this, gen_ctx.replace(expr=expr.this), pos_ctx)
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)

    def _process_rows_from(
        self, expr: exp.TableColumn, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        SELECT * FROM ROWS FROM
        (
            unnest(ARRAY['x', 'y']),
            json_to_recordset('[{"a":40,"b":"foo"}]')
                AS y(a INTEGER, b TEXT),
            generate_series(1, 3)
        ) AS x (name, age, kind, amount)
        """
        downstream_exprs = []
        for table_function in expr.args["rows_from"]:
            # Determine the immediate children of the expression.
            # These are either table functions or aliases to table functions (ColumnDefs)
            cols = list(table_function.find_all(exp.ColumnDef))
            downstream_exprs.extend(cols if cols else [table_function])

        # Get the expression associated with the column name
        child_column_name = gen_ctx.get_child_node().expr.name
        for i, col in enumerate(expr.alias_column_names):
            if col == child_column_name:
                # Returns ColumnDef | Function | Table
                down_expr = downstream_exprs[i]
                if isinstance(down_expr, exp.Table) and down_expr.arg_key == "rows_from":
                    # A table function inside a 'ROWS FROM'
                    down_expr = down_expr.this

                gen_ctx = gen_ctx.replace(expr=down_expr)
                yield from self.process(down_expr, gen_ctx, pos_ctx)
                return

    @process.register
    def process_lateral(
        self, expr: exp.Lateral, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Example query: "SELECT .. LATERAL function() AS t(name)"
        This only handles cases where a function follows LATERAL. If a subquery follows instead,
        its expressions are walked inside walk_query_scope().
        """
        gen_ctx = gen_ctx.replace(expr=expr.this)
        yield from self.process(expr.this, gen_ctx, pos_ctx)

    @process.register
    def process_anonymous(
        self, expr: exp.Anonymous, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        schema, function = util.get_udf_name(expr)

        # Process a sequence
        if not schema and function in [
            "nextval",
            "currval",
            "setval",
            # 'lastval()' is not supported since it requires tracking state
        ]:
            yield from self._process_sequence(expr, gen_ctx, pos_ctx)
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)

    def _process_sequence(
        self, expr: exp.Anonymous, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        seq_name_expr: exp.Literal = expr.args["expressions"][0]
        schema, function = util.get_udf_name(expr)
        full_name = ".".join([schema, function])

        # Ensure the sequence exists
        seq_table = exp.table_(table=seq_name_expr.name, db=schema)
        seq_query = gen_ctx.query.object_mapping.lookup_sequence_query(table=seq_table)
        if not seq_query:
            raise exception.SqlLeafException(f"Sequence '{full_name}' not found.")

        subkind = seq_query.property if seq_query else ""
        gen_ctx = gen_ctx.replace(new_data_type=exp.DataType.build("INT"))
        parent = SequenceNode(name=seq_name_expr.name, gen_ctx=gen_ctx, pos_ctx=pos_ctx, subkind=subkind)
        yield EdgeToCreate(parent, gen_ctx.child_node)

    @process.register
    def process_column_def(
        self, expr: exp.ColumnDef, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        gen_ctx = gen_ctx.replace(new_data_type=expr.kind)

        if isinstance(expr.parent, exp.TableAlias):
            # An alias to a table function inside 'ROWS FROM'
            table_alias = expr.parent.alias_or_name
            if not table_alias:
                # The table alias isn't found - e.g. the "a" in "a(x, y)"
                (before, token, after) = expr.parent.sql().partition("(")
                table_alias = f"{token}{after}"
                raise exception.SqlLeafException(f"The table alias '{table_alias}' must have a name.")

            parent = ColumnNode(
                catalog="",
                schema="",
                table=table_alias,
                column=expr.name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(parent, gen_ctx.child_node)

            # Process the table function
            # TODO: why is this needed? It's 2 levels up
            table_function: exp.Table = t.cast(exp.Table, expr.parent.parent)
            yield from self.do_grandparents([table_function.this], parent, gen_ctx, pos_ctx)

    @process.register
    def process_column(
        self, expr: exp.Column, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        COPY x FROM/TO y
        """
        # TODO: create a new Node called column[kind=table subkind=function] for table functions
        #  (JSON_EACH_TEXT, UNNEST, UDFs that return sets)
        source_info: SourceInfo = gen_ctx.query.source_info

        if SqlObjectType.type_has_no_column_defs(source_info.type):
            if source_info.type == SqlObjectType.FILE:
                gen_ctx = gen_ctx.replace(
                    expr=source_info.expression, new_data_type=gen_ctx.get_child_node().get_data_type()
                )

            node = self.create_node_from_type(
                object_type=source_info.type,
                expression=source_info.expression,
                column_name=gen_ctx.get_child_node().name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(node, gen_ctx.child_node)
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)
