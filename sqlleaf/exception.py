import logging

ERROR_LEVEL = "stop"


logger = logging.getLogger("sqlleaf")


def raise_error(clazz: type, message: str):
    """
    Raise a custom exception based on the error level.
    """
    if ERROR_LEVEL == "stop":
        raise clazz(message)
    elif ERROR_LEVEL == "continue":
        logger.error(message)


def set_error_action(action: str) -> None:
    """
    Set the error level for exceptions.
    """
    if action not in ["continue", "stop"]:
        raise ValueError("The error action must be 'continue' or 'stop'.")

    global ERROR_LEVEL
    ERROR_LEVEL = action


class SqlGlotException(Exception):
    def __init__(self, message, table=""):
        super().__init__(message)

        self.message = message

    def __str__(self):
        return "%s" % (self.message,)


class SqlLeafException(Exception):
    def __init__(self, message):
        super().__init__(message)

        self.message = message

    def __str__(self):
        return "%s" % (self.message,)


class InvalidQueryError(SqlLeafException):
    pass


class UnsupportedFeatureError(SqlLeafException):
    pass


class MappingError(SqlLeafException):
    pass


class GeneratorError(SqlLeafException):
    pass


class GraphError(SqlLeafException):
    pass
