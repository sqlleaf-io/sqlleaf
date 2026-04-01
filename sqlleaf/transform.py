import typing as t
import copy
import logging

import sqlglot
from sqlglot import exp
from sqlglot.optimizer import qualify
from sqlglot.optimizer import annotate_types

from sqlleaf import exception

logger = logging.getLogger("sqleaf")


def apply_optimizations(statement: exp.Expression, dialect: str, mapping, child_table):
    """
    1. We pass validate=false to prevent errors like: sqlglot.errors.OptimizeError: Column '"v_ca_start_date_id"' could not be resolved
    2. We pass infer_schema=True to source unqualified columns from the source table (if missing from the `schema` param)
        e.g. so that
            INSERT INTO my.other
            SELECT name
            FROM my.table
        produces
            my.table.name -> my.other.name
    """
    try:
        stmt = qualify.qualify(
            statement,
            schema=mapping,
            infer_schema=True,
            dialect=dialect,
            isolate_tables=False,
            validate_qualify_columns=False,
            quote_identifiers=False,
        )
    except sqlglot.errors.OptimizeError as e:
        raise exception.SqlGlotException(message=str(e))

    stmt = add_aliases_to_selects(stmt, child_table)
    stmt = annotate_types.annotate_types(stmt, dialect=dialect, schema=mapping)

    return stmt


def add_aliases_to_selects(statement, child_table):
    """
    Add aliases to SELECTs that are missing them by looking at the corresponding INSERT column.
    This prevents sqlglot from assigning its own generated names as aliases.

    For example, the statement:
        INSERT INTO my.apple (a,b) SELECT name, age FROM my.pear
    renames to:
        INSERT INTO my.apple (a,b) SELECT name as a, age as b FROM my.pear
    """
    insert_columns = statement.this.expressions
    if len(insert_columns) > 0 and len(insert_columns) != len(statement.selects):
        message = "Mismatched column count: inserted columns (%s) do not match selected columns (%s)" % (
            len(insert_columns),
            len(statement.selects),
        )
        raise exception.SqlGlotException(message=message, table=child_table)

    for i, ins in enumerate(insert_columns):
        statement.selects[i] = statement.selects[i].as_(ins)
    return statement


def case_statement_transformer(node):
    """
    Transform the 'WHEN' part of every CASE statement so be 1=1 so that the lineage
    does not include the original columns in this clause.

    By default, sqlglot will include columns used in 'WHEN' to the lineage, but they're false positives.
    e.g.
        SELECT CASE WHEN age > 30 THEN 'y' ELSE 'n' END AS approved
    should produce lineage for 'y' and 'n', but not 'age'.

    But if we change it to
        SELECT CASE WHEN 1=1 THEN 'y' ELSE 'n' END AS approved
    then sqlglot will exclude it correctly.

    This is admittedly quite hacky, but it's the cleanest approach considering the limitations of sqlglot's Scope() and
    lineage() functions.
    """
    if isinstance(node, exp.Case):
        case = exp.case()
        for _if in node.args["ifs"]:
            try:
                case = case.when("1=1", then=_if.args["true"])
                if "default" in node.args:
                    case = case.else_(node.args["default"])
            except Exception:
                pass
        return case
    return node


def convert_update_to_insert(statement: sqlglot.exp.Update) -> sqlglot.exp.Select:
    """
    Taken from function extract_select_from_update() at datahub/metadata-ingestion/src/datahub/sql_parsing/sqlglotlineage.py

    This transforms an UPDATE statement into an INSERT statement so that it can be processed by the lineage functions.

    # TODO: explain why w/ example
    """
    _UPDATE_FROM_TABLE_ARGS_TO_MOVE = {"joins", "laterals", "pivot"}
    _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT: t.Set[str] = set(sqlglot.exp.Update.arg_types.keys()) - set(sqlglot.exp.Select.arg_types.keys())

    statement = statement.copy()

    # The "SET" expressions need to be converted.
    # For the update command, it'll be a list of EQ expressions, but the select
    # should contain aliased columns.
    new_expressions = []
    for expr in statement.expressions:
        if isinstance(expr, sqlglot.exp.EQ) and isinstance(expr.left, sqlglot.exp.Column):
            new_expressions.append(
                sqlglot.exp.Alias(
                    this=expr.right,
                    alias=expr.left.this,
                )
            )
        else:
            # If we don't know how to convert it, just leave it as-is. If this causes issues,
            # they'll get caught later.
            new_expressions.append(expr)

    # Special translation for the `from` clause.
    extra_args: dict = {}
    original_from = statement.args.get("from")
    if original_from and isinstance(original_from.this, sqlglot.exp.Table):
        # Move joins, laterals, and pivots from the Update->From->Table->field
        # to the top-level Select->field.

        for k in _UPDATE_FROM_TABLE_ARGS_TO_MOVE:
            if k in original_from.this.args:
                # Mutate the from table clause in-place.
                extra_args[k] = original_from.this.args.get(k)
                original_from.this.set(k, None)

    select_statement = sqlglot.exp.Select(
        **{
            **{k: v for k, v in statement.args.items() if k not in _UPDATE_ARGS_NOT_SUPPORTED_BY_SELECT},
            **extra_args,
            "expressions": new_expressions,
        }
    )

    # Convert the statement into an insert
    insert_statement = exp.insert(expression=select_statement, into=statement.this)
    return insert_statement


def clean_stored_procedure_text(text: str) -> str:
    """
    Extract the queries from inside a stored procedure by removing any
    syntax/keywords that cannot be parsed by sqlglot.

    Parameters:
        text: text containing a stored procedure
    """
    logger.debug("Cleaning stored procedure text.")
    lines = text.splitlines()

    # Transform the procedure's text
    lines = remove_lines_before_begin(lines)
    lines = remove_lines_after_unsupported_syntax(lines)
    lines = remove_raise_statements(lines)

    return "\n".join(lines)


def remove_lines_before_begin(lines: t.List[str], comment=False) -> t.List[str]:
    """
    Remove every line until 'BEGIN', inclusive.

    Parameters:
        lines: list of strings representing a stored procedure
        comment: whether to comment out the matching lines instead of removing them
    """
    stripped_lines = [line.lower().strip() for line in lines]

    # Only process procedures that contain 'begin'
    if "begin" not in stripped_lines:
        return lines

    new_lines = copy.copy(lines)

    # Comment out every line until we reach 'begin'
    for i, line in enumerate(lines):
        l = line.lower().strip()
        if not l.startswith("--"):
            if comment:
                line = "-- " + line
            else:
                line = ""

        # Only overwrite/strip new lines
        new_lines[i] = line
        if l == "begin":
            break

    return new_lines


def remove_lines_after_unsupported_syntax(lines: t.List[str]) -> t.List[str]:
    """
    Remove every line on and after unsupported syntax (e.g. 'EXCEPTION', 'RETURN').

    Parameters:
        lines: list of strings representing a stored procedure
    """
    new_lines = []

    for i, line in enumerate(lines):
        if line.lower().strip().startswith(("exception", "return ")):
            break
        new_lines.append(line)

    return new_lines


def remove_raise_statements(lines: t.List[str]) -> t.List[str]:
    """
    Remove every line starting with 'RAISE'.

    Parameters:
        lines: list of strings representing a stored procedure
    """
    new_lines = []

    for i, line in enumerate(lines):
        if line.lower().strip().startswith("raise "):
            continue
        new_lines.append(line)

    return new_lines
