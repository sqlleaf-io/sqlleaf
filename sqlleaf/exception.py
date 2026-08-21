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
