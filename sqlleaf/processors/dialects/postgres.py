from __future__ import annotations

import logging
import typing as t
from dataclasses import replace

from sqlglot import exp

from sqlleaf import exception, util
from sqlleaf.objects.context import GeneratorContext, PositionContext
from sqlleaf.objects.node_types import (
    ColumnNode,
    FileColumnNode,
    SequenceNode,
    StreamNode,
)
from sqlleaf.objects.query_types import CopyQuery
from sqlleaf.processors.dialects.base import BaseGenerator, EdgeToCreate

logger = logging.getLogger("sqlleaf")


class PostgresGenerator(BaseGenerator):
    dialect = "postgres"

    @util.singledispatchmethodlogger
    def process(self, expr: exp.Expr, gen_ctx: GeneratorContext, pos_ctx: PositionContext) -> t.Iterator[EdgeToCreate]:
        if isinstance(gen_ctx.query, CopyQuery) and isinstance(
            gen_ctx.query.get_original_source(), (exp.Literal, exp.Identifier)
        ):
            # Push all the non-column sources through process_copy for now (until we can do it inside the ColumnNode)
            yield from self.process_copy(expr, gen_ctx, pos_ctx)
        else:
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

                    gen_ctx = replace(gen_ctx, expr=down_expr)
                    yield from self.process(down_expr, gen_ctx, pos_ctx)
                    break
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_anonymous(
        self, expr: exp.Anonymous, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        Either user-defined functions or sequence functions.

        SELECT my.func() or SELECT nextval('my_sequence')
        """
        if isinstance(expr.parent, (exp.Dot,)):
            # Postgres UDFs don't support catalogs
            schema = str(expr.parent.left.name)
            function = str(expr.parent.right.name)
            full_name = f"{schema}.{function}"
        else:
            # e.g. The PG sequence function nextval('serial') is anonymous
            schema = ""
            function = expr.name
            full_name = function

        # Process a sequence
        if not schema and function in [
            "nextval",
            "currval",
            "setval",
        ]:
            # 'lastval()' is not supported since it requires tracking state
            seq_name_expr: exp.Literal = expr.args["expressions"][0]

            # Ensure the sequence exists
            seq_table = exp.table_(table=seq_name_expr.name, db=schema)
            seq_query = gen_ctx.object_mapping.find_query(kind="sequence", table=seq_table)
            if not seq_query:
                logger.warning(f"Sequence '{full_name}' not found.")

            subkind = seq_query.property if seq_query else ""
            parent = SequenceNode(name=seq_name_expr.name, gen_ctx=gen_ctx, pos_ctx=pos_ctx, subkind=subkind)
            yield EdgeToCreate(parent, gen_ctx.child_node)
        else:
            yield from super().process(expr, gen_ctx, pos_ctx)

    @process.register
    def process_column_def(
        self, expr: exp.ColumnDef, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        gen_ctx = replace(gen_ctx, new_data_type=expr.kind)

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
    def process_copy(
        self, expr: exp.Copy, gen_ctx: GeneratorContext, pos_ctx: PositionContext
    ) -> t.Iterator[EdgeToCreate]:
        """
        COPY x FROM/TO y
        """
        source = gen_ctx.query.get_original_source()

        # This logic only processes the query, not the expression
        if source.name in ["stdin", "stdout"]:
            node = StreamNode(
                name=source.name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(node, gen_ctx.child_node)

        elif isinstance(source, exp.Literal):
            # A filename. Create a file node.
            gen_ctx = replace(gen_ctx, expr=source, new_data_type=gen_ctx.get_child_node().get_data_type())
            file_format = util.get_file_format(source.name)
            node = FileColumnNode(
                column=gen_ctx.get_child_node().name,
                file_format=file_format,
                file_path=source.name,
                gen_ctx=gen_ctx,
                pos_ctx=pos_ctx,
            )
            yield EdgeToCreate(node, gen_ctx.child_node)

        else:
            raise exception.SqlLeafException(message=f"Unknown source type for COPY: {type(source)}")
