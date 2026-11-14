import logging
import sys
from enum import StrEnum, auto

logger = logging.getLogger("sqlleaf")

class ErrorLevel(StrEnum):
    ERROR = auto()
    WARN = auto()


ERROR_LEVEL = ErrorLevel.ERROR


def raise_error(cls: type, message: str):
    """
    Raise a custom exception based on the error level.
    """
    if ERROR_LEVEL == ErrorLevel.ERROR:
        raise cls(message).with_traceback(None)
    elif ERROR_LEVEL == ErrorLevel.WARN:
        logger.error(message)


def set_error_action(action: str) -> None:
    """
    Set the error level for exceptions ('error' or 'warn').
    """
    if action not in {level.value for level in ErrorLevel}:
        raise ValueError("The error action must be 'error' or 'warn'.")

    global ERROR_LEVEL
    ERROR_LEVEL = ErrorLevel(action)


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

PRINT_FULL_EXCEPTION = False


def set_print_full_exception(enabled: bool) -> None:
    """
    Set whether uncaught exceptions print the full traceback instead of only the error type and message.
    """
    global PRINT_FULL_EXCEPTION
    PRINT_FULL_EXCEPTION = enabled


def suppress_exception_message(kind, message, traceback):
    if not PRINT_FULL_EXCEPTION and SqlLeafException in kind.__bases__:
        # Short form
        print('{0}: {1}'.format(kind.__name__, message))
    else:
        # Regular form
        sys.__excepthook__(kind, message, traceback)

sys.excepthook = suppress_exception_message
