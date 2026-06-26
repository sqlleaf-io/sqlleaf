class SqlGlotException(Exception):
    def __init__(self, message, table=""):
        super().__init__(message)

        self.message = message
        self.table = table

    def __str__(self):
        if self.table:
            return "%s (Table=%s)" % (self.message, self.table)
        return "%s" % (self.message,)


class SqlLeafException(Exception):
    def __init__(self, message, table=""):
        super().__init__(message)

        self.message = message
        self.table = table

    def __str__(self):
        if self.table:
            return "%s (Table=%s)" % (self.message, self.table)
        return "%s" % (self.message,)
