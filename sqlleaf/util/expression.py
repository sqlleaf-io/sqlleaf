import typing as t

from sqlglot import exp
from sqlglot.optimizer.annotate_types import annotate_types
from sqlglot.optimizer.qualify import qualify

from sqlleaf import exception, mappings, util
from sqlleaf.typing import E, SourceExprType, TargetExprType


def unwrap_expression(expr: E) -> exp.Expr:
    """
    Extract the expression from underneath an Alias or a Paren.
    """
    ex = expr
    while isinstance(ex, (exp.Alias, exp.Paren)):
        ex = ex.unalias()
        if isinstance(ex, (exp.Subquery,)):
            break
        ex = ex.unnest()
    return ex


def copy_expression(expr: E) -> E:
    """
    Copy an expression.

    Unlike sqlglot's copy() method, this preserves the expression's parents.
    """
    for i, ex in enumerate(expr.root().walk()):
        if ex == expr:
            copy_expr = expr.root().copy()
            # Get the equivalent statement in the copy
            for j, new_ex in enumerate(copy_expr.walk()):
                if j == i:
                    return t.cast(E, new_ex)
    return expr


def calculate_function_name(expr: exp.Expr, dialect: str) -> str:
    """
    Remove everything from the first '(' to the last ')' from a string.
    We use this method because exp.Func.sql_name() includes the function's context in its name.
    """
    try:
        # Get the name without its parameters
        name = expr.__class__().sql(dialect=dialect)
    except TypeError, AttributeError:
        # Some classes can't be converted to SQL using this method (e.g. CONCAT() in Postgres)
        name = expr.__class__().sql()
        if not name:
            name = expr.sql(dialect=dialect)

    first_bracket = name.find("(")
    if first_bracket == -1:
        return name

    last_bracket = name.rfind(")")
    if last_bracket == -1:
        return name

    return name[:first_bracket] + name[last_bracket + 1 :]


def find_property(statement: exp.Create, child_object: TargetExprType, dialect: str) -> str:
    """
    Get the table/view's property (e.g. TEMPORARY, EXTERNAL, RECURSIVE)
    """
    if dialect == "redshift" and isinstance(child_object, exp.Table) and child_object.name.startswith("#"):
        return "temporary"

    properties = (exp.TemporaryProperty, exp.ExternalProperty, exp.MaterializedProperty)
    prop = ""
    if props := statement.args.get("properties"):
        prop = str(props.find(properties) or "").lower()
    return prop


def get_location_property(expr: exp.Create, dialect: str) -> str | None:
    """
    Get the LOCATION value from a CREATE statement.
    """
    location = None
    if dialect in ["athena"]:
        if props := expr.args["properties"]:
            if location_expr := props.find(exp.LocationProperty):
                location = location_expr.name
    return location


def column_def_to_column(column_def: exp.ColumnDef, parent_table: t.Optional[exp.Table] = None) -> exp.Column:
    """
    Convert an exp.ColumnDef to an exp.Column
    """
    if parent_table:
        table = parent_table
    elif isinstance(column_def.parent, exp.Schema):
        table: exp.Table = column_def.parent.this
    else:
        table = column_def.parent

    col = exp.column(
        column_def.name,
        table=table.name if table else None,
        db=table.db if table else None,
        catalog=table.catalog if table else None,
    )
    col.type = column_def.kind
    return col


def str_to_column_def(name: str) -> exp.ColumnDef:
    """
    Convert a string into a ColumnDef.
    """
    return exp.ColumnDef(this=exp.to_identifier(name), kind=exp.DType.UNKNOWN.into_expr())


def get_table(expr: exp.Expr) -> exp.Table:
    table = expr.find(exp.Table)
    if table is None:
        raise exception.SqlLeafException(message=f"Could not find an exp.Table in expression: {expr.sql()}")
    return table


def get_udf_name(expr: exp.Anonymous) -> tuple[str, str]:
    """
    Get the schema and function name of a UDF (e.g. from SELECT my.func())
    """
    if isinstance(expr.parent, (exp.Dot,)):
        schema = str(expr.parent.left.name)
        function = str(expr.parent.right.name)
    else:
        # A function without a schema
        schema = ""
        function = expr.name

    return schema, function


def get_function_args(expr: exp.Func) -> t.List[exp.Expr]:
    """
    Get all the argument expressions inside a function.
    Example: "a, b, c" in "SELECT my.func(a,b,c)"
    """
    function_args = list(expr.args.values())
    function_args = util.flatten(function_args)
    exclude = (exp.TableAlias,)  # SELECT FROM UNNEST() AS u
    result = []
    for arg in function_args:
        if arg and isinstance(arg, exp.Expr) and not isinstance(arg, exclude):
            if isinstance(arg, exp.Order):
                # STRING_AGG(Order(Column)) -> Column
                result.append(arg.this)
            else:
                result.append(arg)
    return result


def rename_if_stage(source: SourceExprType, target: TargetExprType) -> None:
    """
    Normalize (uppercase) the name if we are a Snowflake stage.
    sqlglot only normalizes columns - see comments in `sqlglot.optimizer.normalize_identifiers()`
    """
    if str(source).startswith("@"):
        if not str(source).startswith('@"'):
            if isinstance(source, exp.Var):
                source.set("this", str(source).upper())
            else:
                source.this.set("this", str(source).upper())

    elif str(target).startswith("@"):
        if not str(target).startswith('@"'):
            if isinstance(target, exp.Var):
                target.set("this", str(target).upper())
            else:
                target.this.set("this", str(target).upper())


def get_selected_column_names(statement: exp.Expr) -> t.List[str]:
    if isinstance(statement.expression, exp.Values):
        return [s.name for s in statement.this.expressions]
    return [s.alias_or_name for s in statement.selects]


def is_row_function(expr: exp.Expr) -> bool:
    """
    Returns True if the given expression is the ROW() function.
    """
    return isinstance(expr, exp.Anonymous) and expr.this.upper() == "ROW"


def qualify_and_annotate(
    expr: exp.Expr, dialect: str, object_mapping: mappings.ObjectMapping, remove_added_aliases: bool = False
) -> None:
    stmt = qualify(
        expr,
        schema=object_mapping,
        expand_stars=True,
        expand_alias_refs=True,
        qualify_columns=True,
        infer_schema=False,
        dialect=dialect,
        isolate_tables=False,
        validate_qualify_columns=False,
        quote_identifiers=False,
    )

    # Rename the aliases automatically added by sqlglot
    if remove_added_aliases:
        if not isinstance(stmt.expression, exp.Values):
            named_columns = stmt.args["this"].expressions
            for i, ins in enumerate(named_columns):
                # Overwrite the aliases because sqlglot may have added incorrect ones
                if isinstance(ins, exp.ColumnDef):
                    ins = ins.this
                stmt.selects[i] = stmt.selects[i].as_(ins)

    annotate_types(stmt, dialect=dialect, schema=object_mapping)


def get_expression_for_column(column: exp.Column | int, expr: exp.Expr) -> tuple[exp.Expr, int]:
    """
    Get the expression that matches the given column name, along with its index (position) in the SELECT.
    For example, given "SELECT 1 AS a, 2 AS b", column 'b' maps to expression 2.
    """
    if isinstance(column, int):
        # The index of the query in "SELECT 1 UNION SELECT 2"
        select = getattr(expr, "selects")[column]
        idx = column
    else:
        if isinstance(expr, exp.Lateral):
            selects = [(expr, 0)]
        else:
            # Common path
            selects = [
                (select, idx)
                for idx, select in enumerate(getattr(expr, "selects"))
                if select.alias_or_name == column.name
            ]

        if len(selects) > 1:
            message = f"Column reference '{column}' is ambiguous ({len(selects)} possible options)"
            raise exception.SqlLeafException(message)

        if selects:
            select, idx = selects[0]
        else:
            select = expr
            idx = -1
    return select, idx


def get_column_index(column: exp.Column | int, expr: exp.Expr) -> int:
    """
    Return the positional index of a column within a SELECT list.
    Raises if the column cannot be found.
    """
    index = (
        column
        if isinstance(column, int)
        else next(
            (i for i, sel in enumerate(getattr(expr, "selects")) if sel.alias_or_name == column.name),
            -1,  # a negative index should never be returned on success
        )
    )
    if index == -1:
        col_name = column if isinstance(column, int) else column.name
        raise exception.SqlLeafException(message=f"Could not find {col_name} in {expr}")
    return index


def get_column_constraint_expression(expr: exp.ColumnDef) -> exp.ColumnConstraintKind | None:
    """
    Get the DEFAULT or GENERATED expression for this column, if it exists.
    There is only one, but this
    """
    types = (exp.DefaultColumnConstraint, exp.ComputedColumnConstraint)
    constraints = [
        c.kind for c in expr.constraints if isinstance(c, exp.ColumnConstraint) and isinstance(c.kind, types)
    ]
    return t.cast(exp.ColumnConstraintKind, constraints[0]) if constraints else None
