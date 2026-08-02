import typing as t

from sqlglot import exp

from sqlleaf import exception, util
from sqlleaf.typing import E, SourceExprType, TargetExprType
from sqlleaf.util.iterators import default_column_index_iterator


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


def convert_values_to_select(
    expression: exp.Values,
    dialect: str,
    column_names: t.Optional[t.List[str]] = None,
) -> exp.Expr:
    """
    Convert an exp.Values into an exp.Select or exp.Union.
    """
    values_lists: t.List[exp.Tuple] = expression.expressions
    if not values_lists:
        return exp.select("*")

    if not column_names:
        column_names = list(default_column_index_iterator(dialect, values_lists[0].expressions))

    selects = []
    for val_list in values_lists:
        values = val_list.expressions
        cols = [exp.alias_(val, str(col)) for col, val in zip(column_names, values)]
        selects.append(cols)

    if len(selects) > 1:
        new_selects = [exp.select(*select) for select in selects]
        return_expr = exp.union(*new_selects, distinct=False)
    else:
        return_expr = exp.select(*selects[0])

    # Wrap the query in a subquery if it's not a top-level statement
    return return_expr.subquery() if expression.parent_select else return_expr


def is_row_function(expr: exp.Expr) -> bool:
    """
    Returns True if the given expression is the ROW() function.
    """
    return isinstance(expr, exp.Anonymous) and expr.this.upper() == "ROW"
