import typing as t

from sqlglot import exp

from sqlleaf import mappings
from sqlleaf.models.query import FunctionParam, UserDefinedFunctionQuery


def resolve_overloaded_function(
    node: exp.Anonymous, candidates: t.List[UserDefinedFunctionQuery]
) -> t.Optional[UserDefinedFunctionQuery]:
    """
    Resolves the best function candidate for an overloaded function call.
    Applies some precedence rules (e.g., type matching, or non-variadic > variadic) but many are currently
    excluded due to the complexity of the rules.
    """
    if len(candidates) == 1:
        return candidates[0]

    # Function overloading: find the best match based on arguments
    args = node.expressions
    matches = []
    for candidate in candidates:
        if match_arguments(args, candidate):
            matches.append(candidate)

    if not matches:
        raise ValueError(f"No matching function signatures found for args: {args}")

    if len(matches) == 1:
        return matches[0]

    # Preference rule: non-variadic is preferred over variadic
    non_variadic_matches = [m for m in matches if not any(p.is_variadic for p in m.parameters)]
    if non_variadic_matches:
        # Prefer more specific non-variadic matches over polymorphic ones
        specific_matches = [
            m
            for m in non_variadic_matches
            if not any(str(p.type).lower() in ("anyelement", "anyarray") for p in m.parameters)
        ]
        if specific_matches:
            return specific_matches[0]

        # If we only have polymorphic matches, prefer anyarray for array arguments
        if all(arg.type and arg.type.is_type(exp.DataType.Type.ARRAY) for arg in args):
            anyarray_matches = [
                m for m in non_variadic_matches if any(str(p.type).lower() == "anyarray" for p in m.parameters)
            ]
            if anyarray_matches:
                return anyarray_matches[0]

        return non_variadic_matches[0]

    return matches[0]


def match_arguments(args: t.List[exp.Expr], candidate: UserDefinedFunctionQuery) -> bool:
    """
    Checks if the provided arguments match the function candidate's parameters.
    Handles exact types, polymorphic types (anyelement, anyarray), and VARIADIC parameters.
    """
    params = candidate.parameters
    arg_count = len(args)
    param_count = len(params)

    has_variadic = any(p.is_variadic for p in params)

    if not has_variadic:
        if arg_count != param_count:
            return False

        for i, arg in enumerate(args):
            if not match_type(arg, params[i]):
                return False
        return True

    # Variadic function handling
    # Variadic parameter must be the last one
    if arg_count < param_count - 1:
        return False

    # Match mandatory non-variadic parameters
    for i in range(param_count - 1):
        if not match_type(args[i], params[i]):
            return False

    # Match variadic parameters
    variadic_param = params[-1]
    # In Postgres, VARIADIC numeric[] matches foo(1, 2, 3) where each arg is numeric
    # We need to extract the element type from the array type
    variadic_type = variadic_param.type

    element_type = variadic_type
    if variadic_type.is_type(exp.DataType.Type.ARRAY):
        # In sqlglot, ARRAY<INT> has INT as an expression in expressions t.List
        if variadic_type.expressions:
            element_type = variadic_type.expressions[0]
        else:
            # Fallback for simple ARRAY type
            element_type = variadic_type.this

    if isinstance(element_type, exp.DataType):
        element_type = element_type.this

    # If it's VARIADIC anyarray, it matches anything
    is_anyarray = str(variadic_type).lower() == "anyarray"

    for i in range(param_count - 1, arg_count):
        if is_anyarray:
            continue

        target_el_type = (
            exp.DataType.build(element_type) if not isinstance(element_type, exp.DataType) else element_type
        )
        if not match_type_simple(args[i], target_el_type):
            return False

    return True


def match_type(arg: exp.Expr, param: FunctionParam) -> bool:
    """Matches an argument to a parameter, handling polymorphic types."""
    return match_type_simple(arg, param.type)


def match_type_simple(arg: exp.Expr, target_type: exp.DataType) -> bool:
    """Matches an argument expression to a target data type."""
    arg_type = arg.type
    if not arg_type:
        # If type isn't annotated, we can't be sure, but let's try to be lenient or rely on annotate_types
        # In this project, it seems we expect types to be available or we do some basic matching
        return True

    if arg_type.this == exp.DataType.Type.VARCHAR:
        arg_type = exp.DataType.build("TEXT")

    target_type_name = target_type.sql().lower()

    if target_type_name == "anyelement":
        return True
    if target_type_name == "anyarray":
        return arg_type.is_type(exp.DataType.Type.ARRAY)

    # If target is DECIMAL but arg is TEXT, they don't match
    if target_type.is_type(exp.DataType.Type.DECIMAL) and arg_type.is_type(exp.DataType.Type.TEXT):
        return False

    # Handle numeric type matching - Postgres allows implicit cast from literal to numeric
    if target_type.is_type(exp.DataType.Type.DECIMAL):
        if arg_type.is_type(exp.DataType.Type.DOUBLE, exp.DataType.Type.FLOAT, exp.DataType.Type.DECIMAL):
            return True
        # Literals often come as DOUBLE but should match NUMERIC
        if isinstance(arg, (exp.Literal, exp.Cast)):
            return True

    return exp.DataType.is_type(arg_type, target_type)


def find_next_udf_call(
    expression: exp.Expr, object_mapping: mappings.ObjectMapping
) -> t.Tuple[t.Optional[exp.Anonymous], t.Optional[UserDefinedFunctionQuery]]:
    """
    Searches the AST for the next UDF call that matches any of the provided UDF definitions.
    Returns the call node and the matched UDF definition.
    """
    for node in expression.walk():
        if not isinstance(node, exp.Anonymous):
            continue

        # TODO: combine this logic with what's in process_anonymous()
        function_name = node.this.lower()
        # Check if the call is qualified (e.g., myschema.myfunc())
        parent = node.parent
        function_schema = (
            parent.left.name.lower()
            if isinstance(parent, exp.Dot) and isinstance(parent.left, exp.Identifier)
            else None
        )

        udf_object = exp.table_(table=function_name, db=function_schema)
        udf_queries = object_mapping.lookup_udf_query(table=udf_object, raise_on_missing=False)

        candidates = udf_queries
        if not candidates:
            continue


        best_match = resolve_overloaded_function(node, candidates)
        if best_match:
            return node, best_match

    return None, None
